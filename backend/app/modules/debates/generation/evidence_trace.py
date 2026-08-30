"""Pure EvidenceTraceV1 construction and validation.

Evidence trace is a lineage record, not a truth score.  The module deliberately
depends only on the generation DTOs and immutable retrieval receipts.  Database
adapters can persist the returned records atomically with a final-ready turn,
while replay can project the same records without calling retrieval or a model.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .retrieval import TurnSubquery
from .types import (
    EvidenceTraceClaimType,
    EvidenceTraceClaimV1,
    EvidenceTraceSupportMode,
    FinalReadyTurn,
    KeyClaimV1,
    MutualLearningTurnResultV1,
    SnapshotRetrievalReceipt,
)
from .validator import has_explicit_source_claim

EVIDENCE_TRACE_VERSION: Literal["evidence_trace_v1"] = "evidence_trace_v1"
EvidenceTraceQueryKind = Literal[
    "viewpoint", "pending_question", "rebuttal", "updated_position", "context"
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_RE = re.compile(r"^[^/\\\x00\x00-\x1f\x7f]+$")


class EvidenceTraceValidationError(ValueError):
    """A claim, receipt, query or span cannot form a closed trace."""

    def __init__(self, message: str, *, code: str = "evidence_trace_invalid") -> None:
        super().__init__(message)
        self.code = code


class SpeechSpanV1(BaseModel):
    """A non-empty half-open UTF-16 code-unit span into authoritative speech."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_utf16: int = Field(ge=0)
    end_utf16: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_non_empty(self) -> SpeechSpanV1:
        if self.end_utf16 <= self.start_utf16:
            raise ValueError("speech span must be non-empty and half-open")
        return self


class EvidenceTraceQueryV1(BaseModel):
    """Server-authored identity for one exact retrieval subquery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str = Field(min_length=1)
    query_kind: EvidenceTraceQueryKind
    text: str = Field(min_length=1)
    query_hash: str = Field(pattern=_SHA256_RE.pattern)
    turn_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)

    @property
    def query_text(self) -> str:
        """Human-readable alias used by teaching projections."""

        return self.text

    @model_validator(mode="after")
    def validate_hash(self) -> EvidenceTraceQueryV1:
        expected = hashlib.sha256(self.text.strip().encode("utf-8")).hexdigest()
        if self.query_hash != expected:
            raise ValueError("query_hash does not match the exact query text")
        return self


class EvidenceTraceReceiptV1(BaseModel):
    """Public-safe receipt metadata used by an evidence-bearing trace row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    query_id: str | None = Field(default=None, min_length=1)
    query_kind: EvidenceTraceQueryKind | None = None
    query_text: str | None = Field(default=None, min_length=1)
    chunk_id: str = Field(min_length=1)
    source_filename: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1, le=6)
    threshold_key: Literal["strict", "relaxed"]

    @model_validator(mode="after")
    def validate_filename(self) -> EvidenceTraceReceiptV1:
        if not _SAFE_FILENAME_RE.match(self.source_filename):
            raise ValueError("source_filename is unsafe")
        query_fields = (self.query_id, self.query_kind, self.query_text)
        if any(value is not None for value in query_fields) and not all(
            value is not None for value in query_fields
        ):
            raise ValueError("receipt query fields must be supplied together")
        return self


class EvidenceTraceV1(BaseModel):
    """One immutable claim-to-speech/evidence lineage row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_version: Literal["evidence_trace_v1"] = EVIDENCE_TRACE_VERSION
    turn_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: EvidenceTraceClaimType
    query_id: str | None = Field(default=None, min_length=1)
    query_kind: EvidenceTraceQueryKind | None = None
    query_text: str | None = Field(default=None, min_length=1)
    evidence_id: str | None = Field(default=None, min_length=1)
    chunk_id: str | None = Field(default=None, min_length=1)
    source_filename: str | None = Field(default=None, min_length=1)
    source_locator: str | None = Field(default=None, min_length=1)
    support_mode: EvidenceTraceSupportMode
    speech_span: SpeechSpanV1

    @model_validator(mode="after")
    def validate_lineage_shape(self) -> EvidenceTraceV1:
        evidence_fields = (
            self.evidence_id,
            self.chunk_id,
            self.source_filename,
            self.source_locator,
        )
        if self.support_mode in {"direct", "contextual"} and not all(evidence_fields):
            raise ValueError("evidence-bearing trace rows need complete source lineage")
        if self.support_mode in {"general_reasoning", "no_match"} and any(evidence_fields):
            raise ValueError("general/no-match trace rows cannot expose source lineage")
        if self.source_filename is not None and not _SAFE_FILENAME_RE.match(self.source_filename):
            raise ValueError("source_filename is unsafe")
        query_fields = (self.query_id, self.query_kind, self.query_text)
        if any(value is not None for value in query_fields) and not all(
            value is not None for value in query_fields
        ):
            raise ValueError("trace query fields must be supplied together")
        if self.support_mode == "no_match" and any(
            value is not None for value in (self.query_id, self.query_kind, self.query_text)
        ):
            raise ValueError("no-match rows cannot expose a retrieval query")
        return self


@dataclass(frozen=True, slots=True)
class EvidenceTraceBundle:
    """Server-side result containing public rows and private retrieval audit."""

    queries: tuple[EvidenceTraceQueryV1, ...]
    traces: tuple[EvidenceTraceV1, ...]
    receipts: tuple[EvidenceTraceReceiptV1, ...]
    unused_evidence_ids: tuple[str, ...]

    @property
    def public_sources(self) -> tuple[str, ...]:
        """Only evidence referenced by direct/contextual public trace rows."""

        return tuple(
            dict.fromkeys(
                trace.evidence_id
                for trace in self.traces
                if trace.evidence_id is not None and trace.support_mode in {"direct", "contextual"}
            )
        )


def utf16_length(value: str) -> int:
    """Count JavaScript-compatible UTF-16 code units."""

    return len(value.encode("utf-16-le")) // 2


def utf16_slice(value: str, start_utf16: int, end_utf16: int) -> str:
    """Slice a Python string using exact UTF-16 half-open offsets."""

    if start_utf16 < 0 or end_utf16 <= start_utf16:
        raise EvidenceTraceValidationError("UTF-16 span bounds are invalid", code="span_invalid")
    encoded = value.encode("utf-16-le")
    start_byte = start_utf16 * 2
    end_byte = end_utf16 * 2
    if end_byte > len(encoded):
        raise EvidenceTraceValidationError("UTF-16 span exceeds speech", code="span_invalid")
    try:
        return encoded[start_byte:end_byte].decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise EvidenceTraceValidationError(
            "UTF-16 span splits a surrogate pair", code="span_invalid"
        ) from exc


def derive_exact_speech_span(speech: str, claim_text: str) -> SpeechSpanV1:
    """Find one exact claim occurrence and reject ambiguity/non-exact text."""

    if not isinstance(speech, str) or not speech:
        raise EvidenceTraceValidationError(
            "authoritative speech is required", code="speech_invalid"
        )
    if not isinstance(claim_text, str) or not claim_text:
        raise EvidenceTraceValidationError("claim_text is required", code="claim_invalid")
    starts: list[int] = []
    cursor = 0
    while True:
        index = speech.find(claim_text, cursor)
        if index < 0:
            break
        starts.append(index)
        # Advance by one code point so overlapping exact occurrences are also
        # rejected rather than silently selecting one.
        cursor = index + 1
    if not starts:
        raise EvidenceTraceValidationError(
            "claim_text is not an exact speech slice", code="span_non_exact"
        )
    if len(starts) != 1:
        raise EvidenceTraceValidationError(
            "claim_text has an ambiguous speech occurrence", code="span_ambiguous"
        )
    start = starts[0]
    end = start + len(claim_text)
    return SpeechSpanV1(
        start_utf16=utf16_length(speech[:start]),
        end_utf16=utf16_length(speech[:end]),
    )


def validate_exact_speech_span(
    speech: str,
    claim_text: str,
    span: SpeechSpanV1 | Mapping[str, object],
) -> SpeechSpanV1:
    """Validate a caller-provided span against exact authoritative speech."""

    try:
        typed = span if isinstance(span, SpeechSpanV1) else SpeechSpanV1.model_validate(span)
    except Exception as exc:
        raise EvidenceTraceValidationError(
            "speech span shape is invalid", code="span_invalid"
        ) from exc
    try:
        sliced = utf16_slice(speech, typed.start_utf16, typed.end_utf16)
    except EvidenceTraceValidationError:
        raise
    if sliced != claim_text:
        raise EvidenceTraceValidationError(
            "speech span does not contain the exact claim text", code="span_non_exact"
        )
    exact = derive_exact_speech_span(speech, claim_text)
    if typed != exact:
        raise EvidenceTraceValidationError(
            "speech span is not the unique exact occurrence", code="span_non_exact"
        )
    return typed


def derive_source_locator(
    source_document_id: str,
    start_offset: int,
    end_offset: int,
    *,
    normalized_source: str | None = None,
) -> str:
    """Build the server-only Markdown locator from code-point offsets."""

    if not isinstance(source_document_id, str) or not source_document_id.strip():
        raise EvidenceTraceValidationError(
            "source document identity is required", code="locator_invalid"
        )
    if "/" in source_document_id or "\\" in source_document_id:
        raise EvidenceTraceValidationError(
            "source document identity is unsafe", code="locator_invalid"
        )
    if (
        not isinstance(start_offset, int)
        or isinstance(start_offset, bool)
        or not isinstance(end_offset, int)
        or isinstance(end_offset, bool)
        or start_offset < 0
        or end_offset <= start_offset
    ):
        raise EvidenceTraceValidationError("source offsets are invalid", code="locator_invalid")
    if normalized_source is not None and end_offset > len(normalized_source):
        raise EvidenceTraceValidationError(
            "source offsets exceed normalized Markdown", code="locator_invalid"
        )
    return f"md:{source_document_id}:chars:{start_offset}-{end_offset}"


def server_query_id(turn_id: str, index: int, query: TurnSubquery) -> str:
    """Derive a stable UUID identity for a server-owned subquery."""

    if index < 0:
        raise EvidenceTraceValidationError("query index is invalid", code="query_invalid")
    return str(
        uuid5(
            NAMESPACE_URL,
            f"maya:{EVIDENCE_TRACE_VERSION}:query:{turn_id}:{index}:{query.query_hash}",
        )
    )


def server_claim_id(turn_id: str, index: int, claim_text: str) -> str:
    """Derive a claim identity after exact speech validation."""

    return str(
        uuid5(NAMESPACE_URL, f"maya:{EVIDENCE_TRACE_VERSION}:claim:{turn_id}:{index}:{claim_text}")
    )


def _query_rows(
    turn_id: str,
    snapshot_id: str,
    queries: Sequence[TurnSubquery | EvidenceTraceQueryV1 | Mapping[str, object]],
) -> tuple[EvidenceTraceQueryV1, ...]:
    rows: list[EvidenceTraceQueryV1] = []
    for index, query in enumerate(queries):
        if isinstance(query, EvidenceTraceQueryV1):
            if query.turn_id != turn_id or query.snapshot_id != snapshot_id:
                raise EvidenceTraceValidationError(
                    "query crossed turn or snapshot boundary", code="query_scope_invalid"
                )
            rows.append(query)
            continue
        if isinstance(query, TurnSubquery):
            rows.append(
                EvidenceTraceQueryV1(
                    query_id=server_query_id(turn_id, index, query),
                    query_kind=cast(EvidenceTraceQueryKind, query.query_kind),
                    text=query.text,
                    query_hash=query.query_hash,
                    turn_id=turn_id,
                    snapshot_id=snapshot_id,
                )
            )
            continue
        try:
            candidate = EvidenceTraceQueryV1.model_validate(query)
        except Exception as exc:
            raise EvidenceTraceValidationError(
                "query shape is invalid", code="query_invalid"
            ) from exc
        if candidate.turn_id != turn_id or candidate.snapshot_id != snapshot_id:
            raise EvidenceTraceValidationError(
                "query crossed turn or snapshot boundary", code="query_scope_invalid"
            )
        rows.append(candidate)
    ids = [row.query_id for row in rows]
    if len(ids) != len(set(ids)):
        raise EvidenceTraceValidationError(
            "query IDs must be unique within a turn", code="query_invalid"
        )
    signatures = [(row.query_kind, row.query_hash) for row in rows]
    if len(signatures) != len(set(signatures)):
        raise EvidenceTraceValidationError(
            "duplicate retrieval queries are ambiguous", code="query_invalid"
        )
    return tuple(rows)


def _receipt_row(
    receipt: SnapshotRetrievalReceipt | EvidenceTraceReceiptV1 | Mapping[str, object],
    *,
    query_rows: Sequence[EvidenceTraceQueryV1],
    snapshot_id: str,
) -> EvidenceTraceReceiptV1:
    if isinstance(receipt, EvidenceTraceReceiptV1):
        row = receipt
    elif isinstance(receipt, SnapshotRetrievalReceipt):
        if receipt.snapshot_id != snapshot_id:
            raise EvidenceTraceValidationError(
                "receipt crossed the participant snapshot", code="receipt_scope_invalid"
            )
        matching = next(
            (
                query
                for query in query_rows
                if query.query_kind == receipt.query_kind and query.query_hash == receipt.query_hash
            ),
            None,
        )
        source_document_id = getattr(receipt, "source_document_id", None)
        source_start = getattr(receipt, "source_start_offset", None)
        source_end = getattr(receipt, "source_end_offset", None)
        if (
            not isinstance(source_document_id, str)
            or not isinstance(source_start, int)
            or isinstance(source_start, bool)
            or not isinstance(source_end, int)
            or isinstance(source_end, bool)
        ):
            raise EvidenceTraceValidationError(
                "receipt has no server-derived source locator", code="receipt_invalid"
            )
        row = EvidenceTraceReceiptV1(
            evidence_id=receipt.resolved_evidence_id(),
            snapshot_id=receipt.snapshot_id,
            query_id=matching.query_id if matching else receipt.query_id,
            query_kind=(
                matching.query_kind
                if matching
                else (
                    cast(EvidenceTraceQueryKind, receipt.query_kind)
                    if receipt.query_id
                    else None
                )
            ),
            query_text=matching.text if matching else None,
            chunk_id=receipt.chunk_id,
            source_filename=receipt.source_filename,
            source_locator=derive_source_locator(source_document_id, source_start, source_end),
            excerpt=receipt.excerpt or receipt.text,
            score=receipt.score,
            rank=receipt.rank,
            threshold_key=receipt.threshold_key,
        )
    else:
        try:
            row = EvidenceTraceReceiptV1.model_validate(receipt)
        except Exception as exc:
            raise EvidenceTraceValidationError(
                "receipt shape is invalid", code="receipt_invalid"
            ) from exc
    if row.snapshot_id != snapshot_id:
        raise EvidenceTraceValidationError(
            "receipt crossed the participant snapshot", code="receipt_scope_invalid"
        )
    if row.query_id is not None and row.query_id not in {query.query_id for query in query_rows}:
        raise EvidenceTraceValidationError(
            "receipt query is not part of this turn", code="query_scope_invalid"
        )
    if row.query_id is not None:
        query = next(query for query in query_rows if query.query_id == row.query_id)
        if row.query_kind is not None and row.query_kind != query.query_kind:
            raise EvidenceTraceValidationError(
                "receipt query kind does not match its query", code="query_scope_invalid"
            )
        if row.query_text is not None and row.query_text != query.text:
            raise EvidenceTraceValidationError(
                "receipt query text does not match its query", code="query_scope_invalid"
            )
    return row


def _claim_input(value: object) -> EvidenceTraceClaimV1:
    if isinstance(value, EvidenceTraceClaimV1):
        return value
    if isinstance(value, KeyClaimV1):
        # Mutual-learning's interpretation vocabulary is an internal claim
        # label; EvidenceTrace exposes the frozen background vocabulary.
        claim_type = "background" if value.claim_type == "interpretation" else value.claim_type
        return EvidenceTraceClaimV1(
            claim_text=value.claim_text,
            claim_type=claim_type,
            used_evidence_ids=list(value.used_evidence_ids),
        )
    if isinstance(value, Mapping) and value.get("claim_type") == "interpretation":
        value = {**value, "claim_type": "background"}
    try:
        return EvidenceTraceClaimV1.model_validate(value)
    except Exception as exc:
        raise EvidenceTraceValidationError(
            "teaching claim shape is invalid", code="claim_invalid"
        ) from exc


def build_evidence_trace_bundle(
    turn_id: str,
    speech: str,
    claims: Sequence[EvidenceTraceClaimV1 | KeyClaimV1 | Mapping[str, object]],
    receipts: Sequence[
        SnapshotRetrievalReceipt | EvidenceTraceReceiptV1 | Mapping[str, object]
    ] = (),
    queries: Sequence[TurnSubquery | EvidenceTraceQueryV1 | Mapping[str, object]] = (),
    *,
    snapshot_id: str | None = None,
) -> EvidenceTraceBundle:
    """Validate claims and derive a public-safe immutable trace bundle."""

    if not turn_id:
        raise EvidenceTraceValidationError(
            "turn and snapshot identities are required", code="scope_invalid"
        )
    if snapshot_id is None:
        snapshot_ids = {
            item.snapshot_id
            for item in receipts
            if isinstance(item, (SnapshotRetrievalReceipt, EvidenceTraceReceiptV1))
        }
        snapshot_ids.update(
            str(item["snapshot_id"])
            for item in receipts
            if isinstance(item, Mapping) and isinstance(item.get("snapshot_id"), str)
        )
        if len(snapshot_ids) == 1:
            snapshot_id = next(iter(snapshot_ids))
        else:
            raise EvidenceTraceValidationError(
                "snapshot identity is required when receipts are empty or mixed",
                code="scope_invalid",
            )
    if not 1 <= len(claims) <= 12:
        raise EvidenceTraceValidationError(
            "a turn needs 1-12 teaching claims", code="claim_count_invalid"
        )
    query_rows = _query_rows(turn_id, snapshot_id, queries)
    receipt_rows = tuple(
        _receipt_row(item, query_rows=query_rows, snapshot_id=snapshot_id) for item in receipts
    )
    receipt_ids = [item.evidence_id for item in receipt_rows]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise EvidenceTraceValidationError(
            "receipt IDs must be unique within a turn", code="receipt_invalid"
        )
    receipt_map = {item.evidence_id: item for item in receipt_rows}
    traces: list[EvidenceTraceV1] = []
    used_ids: set[str] = set()
    seen_claim_text: set[str] = set()
    for index, raw_claim in enumerate(claims):
        claim = _claim_input(raw_claim)
        if claim.claim_text in seen_claim_text:
            raise EvidenceTraceValidationError(
                "duplicate claim text makes the trace ambiguous", code="claim_ambiguous"
            )
        seen_claim_text.add(claim.claim_text)
        span = derive_exact_speech_span(speech, claim.claim_text)
        evidence_ids = tuple(dict.fromkeys(claim.used_evidence_ids))
        if len(evidence_ids) != len(claim.used_evidence_ids):
            raise EvidenceTraceValidationError(
                "evidence IDs must be unique within a claim", code="receipt_invalid"
            )
        if any(not item for item in evidence_ids):
            raise EvidenceTraceValidationError(
                "evidence IDs must be non-empty", code="receipt_invalid"
            )
        unknown = [item for item in evidence_ids if item not in receipt_map]
        if unknown:
            raise EvidenceTraceValidationError(
                "claim references an unknown or cross-request receipt", code="receipt_scope_invalid"
            )
        if claim.support_mode in {"general_reasoning", "no_match"} and evidence_ids:
            raise EvidenceTraceValidationError(
                "a source-bearing claim cannot be general reasoning/no-match",
                code="support_mode_invalid",
            )
        if evidence_ids:
            support_mode = claim.support_mode or "direct"
        elif receipt_rows:
            support_mode = claim.support_mode or "general_reasoning"
        else:
            support_mode = claim.support_mode or "no_match"
        if support_mode == "no_match" and receipt_rows:
            raise EvidenceTraceValidationError(
                "no-match is only valid when retrieval has no qualifying receipt",
                code="support_mode_invalid",
            )
        if claim.claim_type in {"factual", "background"} and has_explicit_source_claim(
            claim.claim_text
        ):
            if not evidence_ids or support_mode != "direct":
                raise EvidenceTraceValidationError(
                    "quantities and source attributions require direct evidence",
                    code="direct_evidence_required",
                )
        if support_mode in {"direct", "contextual"}:
            for evidence_id in evidence_ids:
                used_ids.add(evidence_id)
        query_id = receipt_map[evidence_ids[0]].query_id if evidence_ids else None
        query = next((item for item in query_rows if item.query_id == query_id), None)
        evidence_values: tuple[str | None, ...] = evidence_ids or (None,)
        for trace_evidence_id in evidence_values:
            receipt = (
                receipt_map.get(trace_evidence_id) if trace_evidence_id else None
            )
            traces.append(
                EvidenceTraceV1(
                    turn_id=turn_id,
                    claim_id=server_claim_id(turn_id, index, claim.claim_text),
                    claim_text=claim.claim_text,
                    claim_type=claim.claim_type,
                    query_id=query.query_id if query else (receipt.query_id if receipt else None),
                    query_kind=query.query_kind
                    if query
                    else (receipt.query_kind if receipt else None),
                    query_text=query.text if query else (receipt.query_text if receipt else None),
                    evidence_id=receipt.evidence_id if receipt else None,
                    chunk_id=receipt.chunk_id if receipt else None,
                    source_filename=receipt.source_filename if receipt else None,
                    source_locator=receipt.source_locator if receipt else None,
                    support_mode=support_mode,
                    speech_span=span,
                )
            )
    direct_traces = [item for item in traces if item.support_mode == "direct"]
    for sentence in re.findall(r"[^.!?]+[.!?]", speech):
        if has_explicit_source_claim(sentence.strip()) and not any(
            sentence.strip() in item.claim_text and item.claim_type in {"factual", "background"}
            for item in direct_traces
        ):
            raise EvidenceTraceValidationError(
                "a concrete/source sentence lacks a direct factual trace",
                code="direct_evidence_required",
            )
    unused = tuple(item.evidence_id for item in receipt_rows if item.evidence_id not in used_ids)
    return EvidenceTraceBundle(
        queries=query_rows,
        traces=tuple(traces),
        receipts=receipt_rows,
        unused_evidence_ids=unused,
    )


def build_evidence_trace(
    turn_id: str,
    speech: str,
    claims: Sequence[EvidenceTraceClaimV1 | KeyClaimV1 | Mapping[str, object]],
    receipts: Sequence[
        SnapshotRetrievalReceipt | EvidenceTraceReceiptV1 | Mapping[str, object]
    ] = (),
    queries: Sequence[TurnSubquery | EvidenceTraceQueryV1 | Mapping[str, object]] = (),
    *,
    snapshot_id: str | None = None,
) -> tuple[EvidenceTraceV1, ...]:
    """Convenience API returning only public trace rows."""

    return build_evidence_trace_bundle(
        turn_id,
        speech,
        claims,
        receipts,
        queries,
        snapshot_id=snapshot_id,
    ).traces


def build_mutual_learning_evidence_trace(
    turn: FinalReadyTurn,
    *,
    queries: Sequence[TurnSubquery | EvidenceTraceQueryV1 | Mapping[str, object]] = (),
) -> EvidenceTraceBundle | None:
    """Compile optional exact teaching claims from a validated mutual turn."""

    if not isinstance(turn.structured, MutualLearningTurnResultV1):
        return None
    claims = getattr(turn.structured, "evidence_trace_claims", ())
    if not claims:
        # The original Mock DTO uses concise summaries rather than guaranteed
        # exact speech slices.  Reuse key claims only when every one is an
        # exact, unique speech slice; otherwise do not invent provenance.
        candidates = getattr(turn.structured, "key_claims", ())
        try:
            for claim in candidates:
                derive_exact_speech_span(turn.speech, claim.claim_text)
        except ValueError:
            return None
        claims = candidates
    if not claims:
        return None
    return build_evidence_trace_bundle(
        turn.turn_id,
        turn.speech,
        claims,
        turn.used_receipts,
        queries,
        snapshot_id=turn.snapshot_id,
    )


def align_mutual_learning_claim_ids(
    result: MutualLearningTurnResultV1,
    bundle: EvidenceTraceBundle,
) -> MutualLearningTurnResultV1:
    """Replace provider claim IDs with the server IDs used by trace rows.

    The provider may describe claims but never owns their identity.  When an
    exact trace catalog is present, every structured key claim must have the
    same exact speech text in that catalog; otherwise an engagement could
    point at an ID that has no corresponding lineage row.
    """

    if not result.evidence_trace_claims and not bundle.traces:
        return result
    ids_by_text: dict[str, str] = {}
    for trace in bundle.traces:
        ids_by_text.setdefault(trace.claim_text, trace.claim_id)
    missing = [
        claim.claim_text
        for claim in result.key_claims
        if claim.claim_text not in ids_by_text
    ]
    if missing:
        raise EvidenceTraceValidationError(
            "every mutual key claim needs an exact evidence trace row",
            code="claim_alignment_invalid",
        )
    key_evidence_ids = {
        evidence_id
        for claim in result.key_claims
        for evidence_id in claim.used_evidence_ids
    }
    trace_evidence_ids = {
        trace.evidence_id
        for trace in bundle.traces
        if trace.evidence_id is not None
    }
    if key_evidence_ids != trace_evidence_ids:
        raise EvidenceTraceValidationError(
            "mutual key-claim and evidence-trace receipts differ",
            code="claim_alignment_invalid",
        )
    claims = [
        claim.model_copy(update={"claim_id": ids_by_text[claim.claim_text]})
        for claim in result.key_claims
    ]
    return result.model_copy(update={"key_claims": claims})


def public_evidence_trace(value: object) -> tuple[EvidenceTraceV1, ...]:
    """Project trace rows while dropping unused receipt audit data."""

    if isinstance(value, EvidenceTraceBundle):
        return value.traces
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows: list[EvidenceTraceV1] = []
        for item in value:
            try:
                if isinstance(item, EvidenceTraceV1):
                    rows.append(item)
                    continue
                if isinstance(item, Mapping):
                    payload = dict(item)
                elif hasattr(item, "model_dump"):
                    payload = item.model_dump(mode="json")
                else:
                    payload = {
                        name: getattr(item, name)
                        for name in (
                            "trace_version",
                            "turn_id",
                            "claim_id",
                            "claim_text",
                            "claim_type",
                            "query_id",
                            "query_kind",
                            "query_text",
                            "evidence_id",
                            "chunk_id",
                            "source_filename",
                            "source_locator",
                            "support_mode",
                            "speech_span",
                        )
                        if hasattr(item, name)
                    }
                # ORM trace rows may retain private receipt/query columns.  A
                # public projection copies only the frozen trace contract.
                allowed = {
                    "trace_version",
                    "turn_id",
                    "claim_id",
                    "claim_text",
                    "claim_type",
                    "query_id",
                    "query_kind",
                    "query_text",
                    "evidence_id",
                    "chunk_id",
                    "source_filename",
                    "source_locator",
                    "support_mode",
                    "speech_span",
                }
                payload = {key: payload[key] for key in allowed if key in payload}
                if "speech_span" not in payload:
                    start = getattr(item, "start_utf16", None)
                    end = getattr(item, "end_utf16", None)
                    if start is not None and end is not None:
                        payload["speech_span"] = {
                            "start_utf16": start,
                            "end_utf16": end,
                        }
                rows.append(EvidenceTraceV1.model_validate(payload))
            except Exception as exc:
                raise EvidenceTraceValidationError(
                    "trace row is invalid", code="trace_invalid"
                ) from exc
        return tuple(rows)
    raise EvidenceTraceValidationError("trace projection is not a sequence", code="trace_invalid")


# Naming aliases keep the adapter seam discoverable without duplicating logic.
EvidenceTrace = EvidenceTraceV1
EvidenceTraceQuery = EvidenceTraceQueryV1
EvidenceTraceReceipt = EvidenceTraceReceiptV1
SpeechSpan = SpeechSpanV1
derive_speech_span = derive_exact_speech_span
compile_evidence_trace = build_evidence_trace_bundle


__all__ = [
    "EVIDENCE_TRACE_VERSION",
    "EvidenceTrace",
    "EvidenceTraceBundle",
    "EvidenceTraceClaimType",
    "EvidenceTraceClaimV1",
    "EvidenceTraceQuery",
    "EvidenceTraceQueryKind",
    "EvidenceTraceQueryV1",
    "EvidenceTraceReceipt",
    "EvidenceTraceReceiptV1",
    "EvidenceTraceSupportMode",
    "EvidenceTraceV1",
    "EvidenceTraceValidationError",
    "SpeechSpan",
    "SpeechSpanV1",
    "build_evidence_trace",
    "build_evidence_trace_bundle",
    "build_mutual_learning_evidence_trace",
    "align_mutual_learning_claim_ids",
    "compile_evidence_trace",
    "derive_exact_speech_span",
    "derive_source_locator",
    "derive_speech_span",
    "public_evidence_trace",
    "server_claim_id",
    "server_query_id",
    "utf16_length",
    "utf16_slice",
    "validate_exact_speech_span",
]
