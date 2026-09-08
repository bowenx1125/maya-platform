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

from .schemas import ReportDiscussionMemory, ReportScoreSummary, ReportSectionOutput

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


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportParticipant(_ClosedModel):
    """A public Agent projection, intentionally without Agent/Persona IDs."""

    slot: Slot
    agent_name: str = Field(min_length=1, max_length=160)


class ReportSpeech(_ClosedModel):
    """One public final-ready speech and only the evidence it actually used."""

    slot: Slot
    round_no: int = Field(ge=1, le=5)
    turn_index: int = Field(ge=0, le=999)
    speech: str = Field(min_length=1, max_length=8000)
    used_evidence_ids: tuple[str, ...] = ()


class ReportSource(_ClosedModel):
    """A used TurnSource projection with no filename, path or full chunk."""

    # Retrieval receipts use opaque ``evidence-*`` keys in addition to UUID
    # fixtures.  The provider never authors or resolves this key; the service
    # maps it back to the immutable TurnSource row when rendering citations.
    evidence_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    excerpt: str = Field(min_length=1)


class ReportBarrage(_ClosedModel):
    """An already-anonymized frozen classroom message for v2 reports."""

    barrage_id: str = Field(min_length=2, max_length=16, pattern=r"^B[1-9][0-9]*$")
    turn_index: int = Field(ge=0, le=999)
    text: str = Field(min_length=1, max_length=300)


class ReportReply(_ClosedModel):
    """A real paragraph-to-barrage binding from a final segment turn."""

    barrage_id: str = Field(min_length=2, max_length=16, pattern=r"^B[1-9][0-9]*$")
    slot: Slot
    turn_index: int = Field(ge=0, le=999)
    paragraph_index: int = Field(ge=0, le=99)


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

    topic: str = Field(min_length=1)
    participants: tuple[ReportParticipant, ...] = Field(min_length=2, max_length=5)
    speeches: tuple[ReportSpeech, ...] = Field(min_length=1, max_length=10)
    sources: tuple[ReportSource, ...] = Field(default=(), max_length=64)
    votes: tuple[ReportVote, ...] = Field(default=(), max_length=5)
    insights: tuple[ReportInsight, ...] = Field(default=(), max_length=32)
    # The language the debate was generated in. The report is written in
    # English either way; this only tells the input scan what to expect.
    source_language: Literal["en", "zh"] = "en"

    @model_validator(mode="after")
    def validate_closed_boundary(self) -> ReportRequest:
        _validate_request_semantics(self)
        return self

    def canonical_payload(self) -> dict[str, object]:
        """Return deterministic provider-visible data, excluding private IDs."""

        payload = cast(dict[str, object], self.model_dump(mode="json"))
        # Bind Chinese output language into the frozen request while retaining
        # the canonical default-English shape.
        if self.source_language == "en":
            payload.pop("source_language", None)
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


def _validate_request_semantics(request: ReportRequest) -> None:
    # Validate projected relationships, not the wording of classroom data.
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
        str(evidence_id) for speech in request.speeches for evidence_id in speech.used_evidence_ids
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


class ReportRequestV2(ReportRequest):
    """Versioned report input for 2–5-round segment Debates."""

    protocol_version: Literal["segments_v2"] = "segments_v2"
    speeches: tuple[ReportSpeech, ...] = Field(min_length=1, max_length=25)
    sources: tuple[ReportSource, ...] = Field(default=(), max_length=150)
    classroom_barrages: tuple[ReportBarrage, ...] = ()
    replies: tuple[ReportReply, ...] = ()
    # Code-owned, deterministic classroom grading.  Omit for an older stored
    # v2 manifest so its request hash remains stable during recovery.
    score_summary: ReportScoreSummary | None = None
    discussion_memories: tuple[ReportDiscussionMemory, ...] = ()

    @model_validator(mode="after")
    def validate_v2_semantics(self) -> ReportRequestV2:
        slots = {item.slot for item in self.participants}
        memory_slots = [item.slot for item in self.discussion_memories]
        if len(memory_slots) != len(set(memory_slots)) or not set(memory_slots).issubset(slots):
            raise ReportBoundaryError("report_memory_projection")
        for memory in self.discussion_memories:
            if memory.influence is not None and memory.influence.slot not in slots:
                raise ReportBoundaryError("report_memory_projection")
        barrage_ids = [item.barrage_id for item in self.classroom_barrages]
        if len(barrage_ids) != len(set(barrage_ids)):
            raise ReportBoundaryError("report_duplicate_barrage")
        if any(reply.barrage_id not in set(barrage_ids) for reply in self.replies):
            raise ReportBoundaryError("report_reply_not_available")
        speech_keys = {(speech.round_no, speech.turn_index) for speech in self.speeches}
        if any((reply.turn_index not in {key[1] for key in speech_keys}) for reply in self.replies):
            raise ReportBoundaryError("report_reply_turn_unknown")
        reply_keys = [
            (reply.slot, reply.turn_index, reply.paragraph_index, reply.barrage_id)
            for reply in self.replies
        ]
        if len(reply_keys) != len(set(reply_keys)):
            raise ReportBoundaryError("report_duplicate_reply")
        if self.score_summary is not None and {item.slot for item in self.score_summary.agents} != {
            item.slot for item in self.participants
        }:
            raise ReportBoundaryError("report_score_projection")
        return self

    def canonical_payload(self) -> dict[str, object]:
        payload = super().canonical_payload()
        if not payload.get("discussion_memories"):
            payload.pop("discussion_memories", None)
        else:
            payload["discussion_memories"] = sorted(
                cast(list[dict[str, object]], payload["discussion_memories"]),
                key=lambda row: str(row["slot"]),
            )
        if payload.get("score_summary") is None:
            payload.pop("score_summary", None)
        elif isinstance(payload.get("score_summary"), dict):
            score_summary = cast(dict[str, object], payload["score_summary"])
            agents = score_summary.get("agents")
            if isinstance(agents, list):
                score_summary["agents"] = sorted(
                    cast(list[dict[str, object]], agents),
                    key=lambda row: str(row["slot"]),
                )
        payload["classroom_barrages"] = sorted(
            cast(list[dict[str, object]], payload["classroom_barrages"]),
            key=lambda row: (str(row["barrage_id"]), int(cast(int, row["turn_index"]))),
        )
        payload["replies"] = sorted(
            cast(list[dict[str, object]], payload["replies"]),
            key=lambda row: (
                int(cast(int, row["turn_index"])),
                int(cast(int, row["paragraph_index"])),
                str(row["slot"]),
                str(row["barrage_id"]),
            ),
        )
        return payload


def validate_report_request(value: ReportRequest | Mapping[str, object]) -> ReportRequest:
    """Validate a request while exposing only a safe boundary code."""

    if isinstance(value, ReportRequest):
        return value
    try:
        if isinstance(value, Mapping) and value.get("protocol_version") == "segments_v2":
            return ReportRequestV2.model_validate(value)
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
    """Validate the six-field shape; prose rules belong to the actual prompt."""

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
        if not isinstance(text_value, str) or not text_value.strip():
            raise ReportBoundaryError("report_output_schema")
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
    "ReportBarrage",
    "ReportEvidence",
    "ReportInsight",
    "ReportParticipant",
    "ReportParticipantInput",
    "ReportRequest",
    "ReportRequestV2",
    "ReportReply",
    "ReportSource",
    "ReportSpeech",
    "ReportSpeechInput",
    "ReportVote",
    "Slot",
    "validate_report_request",
    "validate_report_sections",
]
