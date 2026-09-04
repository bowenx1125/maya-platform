"""Canonical provider request assembly for the mutual-learning RuleSet.

This module is a provider-neutral boundary.  It turns already frozen server
state into two provider-visible messages: one rules system message and one
canonical JSON user message.  It intentionally does not load a database,
retrieve evidence, or call a model.  Retrieval results are supplied as typed
receipts and are copied into a deduplicated, source-name-free evidence
catalogue.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.persona import (
    PersonaProviderViewV1,
    PersonaSpecV1,
    persona_spec_hash,
    provider_view,
)

from .mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from .mutual_learning_prompts import (
    MUTUAL_LEARNING_PLATFORM_RULES,
    mutual_learning_platform_rules,
)
from .prompt_budget import (
    MAX_OUTPUT_TOKENS,
    PromptBudgetV1,
    TokenCounterPort,
    preflight_prompt_budget,
)
from .round_phase import RoundPhase, resolve_round_phase
from .types import FinalReadyTurn, GenerationContext, PendingQuestion, SnapshotRetrievalReceipt

if TYPE_CHECKING:
    from .types import MutualLearningPromptInput

PROMPT_REQUEST_VERSION: Literal["prompt_request_v1"] = "prompt_request_v1"
PROMPT_SYSTEM_VERSION: Literal["prompt_system_v1"] = "prompt_system_v1"
PROMPT_OUTPUT_SCHEMA_ID: Literal["mutual_learning_turn_result_v1"] = (
    "mutual_learning_turn_result_v1"
)
PROMPT_EVIDENCE_TRACE_SCHEMA_ID: Literal["evidence_trace_v1"] = "evidence_trace_v1"

# Matches contracts/llm-repair-feedback.v1.schema.json, which is the frozen
# grammar these pointers are serialized into. A narrower rule here does not make
# the wire safer: it makes the runtime discard a precise pointer and fall back
# to "/", which is the whole information the second attempt had to work with.
_POINTER_RE = re.compile(r"^/(?:[^~/]|~[01])*(?:/(?:[^~/]|~[01])*)*$|^$")


class PromptRequestError(ValueError):
    """A provider request failed the closed, pre-send request contract."""

    def __init__(self, message: str, *, code: str = "prompt_request_invalid") -> None:
        super().__init__(message)
        self.code = code


class PromptClosedModel(BaseModel):
    """Immutable closed DTO base; unknown provider fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PromptQuestionV1(PromptClosedModel):
    type: Literal["agent", "audience_reflection", "none"] = "none"
    question_id: str | None = Field(default=None, min_length=1)
    source_turn_id: str | None = Field(default=None, min_length=1)
    source_participant_id: str | None = Field(default=None, min_length=1)
    target_participant_id: str | None = Field(default=None, min_length=1)
    text: str | None = Field(default=None, min_length=1)


class PromptKeyClaimV1(PromptClosedModel):
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: Literal["factual", "interpretation", "value_judgement", "proposal"]
    used_evidence_ids: tuple[str, ...] = ()


class PromptEngagementV1(PromptClosedModel):
    target_turn_id: str = Field(min_length=1)
    target_claim_id: str | None = Field(default=None, min_length=1)
    relation: Literal["agree", "extend", "qualify", "challenge", "reconcile"]
    faithful_summary: str = Field(min_length=1)
    response_summary: str = Field(min_length=1)


class PromptDisagreementV1(PromptClosedModel):
    summary: str = Field(min_length=1)
    category: Literal[
        "different_persona_or_framework",
        "different_evidence",
        "evidence_conflict",
        "insufficient_information",
        "value_tradeoff",
    ]
    claim_ids: tuple[str, ...] = ()


class PromptPredecessorTurnV1(PromptClosedModel):
    """One complete public predecessor turn, without private row fields."""

    turn_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    round_no: int = Field(ge=1)
    turn_index: int = Field(ge=0)
    speech: str = Field(min_length=1)
    key_claims: tuple[PromptKeyClaimV1, ...] = ()
    engagements: tuple[PromptEngagementV1, ...] = ()
    answered_question_ids: tuple[str, ...] = ()
    learned_from_others: tuple[str, ...] = ()
    position_summary: str = ""
    position_update: str | None = None
    position_update_reason: str | None = None
    remaining_uncertainty: tuple[str, ...] = ()
    unresolved_issue: str | None = None
    question: PromptQuestionV1 = Field(default_factory=PromptQuestionV1)
    missing_information: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    change_from_opening: str | None = None
    final_consensus: tuple[str, ...] = ()
    final_disagreements: tuple[PromptDisagreementV1, ...] = ()
    final_recommendation: str | None = None
    used_evidence_ids: tuple[str, ...] = ()


class PromptPendingQuestionV1(PromptClosedModel):
    """The single required question assigned to the current participant."""

    question_id: str = Field(min_length=1)
    source_turn_id: str = Field(min_length=1)
    source_participant_id: str = Field(min_length=1)
    target_participant_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PromptQueryV1(PromptClosedModel):
    query_id: str = Field(min_length=1)
    query_kind: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    query_hash: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.query_id

    @property
    def text(self) -> str:
        return self.query_text


class PromptEvidenceV1(PromptClosedModel):
    """Provider-safe evidence: opaque ID, query links and exact excerpt only."""

    evidence_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    query_ids: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return self.excerpt


class PromptRepairFeedbackV1(PromptClosedModel):
    """Safe structure-repair feedback; no raw provider message is accepted."""

    safe_error_code: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,79}$",
        validation_alias=AliasChoices("safe_error_code", "error_code", "code"),
    )
    json_pointers: tuple[str, ...] = Field(
        default=(),
        max_length=32,
        validation_alias=AliasChoices("json_pointers", "pointers", "json_pointer"),
    )

    @model_validator(mode="after")
    def validate_pointers(self) -> PromptRepairFeedbackV1:
        if any(not _POINTER_RE.fullmatch(pointer) for pointer in self.json_pointers):
            raise ValueError("repair feedback contains an invalid JSON pointer")
        if any(len(pointer) > 240 for pointer in self.json_pointers):
            raise ValueError("repair feedback JSON pointer is too long")
        return self

    @property
    def error_code(self) -> str:
        return self.safe_error_code

    @property
    def pointers(self) -> tuple[str, ...]:
        return self.json_pointers


class PromptRequestV1(PromptClosedModel):
    """Canonical logical request sent as the sole user JSON message."""

    request_version: Literal["prompt_request_v1"] = PROMPT_REQUEST_VERSION
    debate_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    rule_set_id: str = Field(min_length=1)
    rule_set_hash: str = Field(min_length=1)
    phase: Literal["opening", "exchange", "final_integration"]
    round_no: int = Field(ge=1)
    round_count: int | None = Field(default=None, ge=2)
    turn_index: int = Field(ge=0)
    participant_id: str = Field(min_length=1)
    participant_slot: str = Field(min_length=1)
    participant_order_index: int = Field(ge=0)
    next_participant_id: str | None = Field(default=None, min_length=1)
    is_final_round: bool
    is_final_turn: bool
    topic: str = Field(min_length=1)
    assigned_stance: str | None = Field(default=None, min_length=1)
    persona_provider_view: PersonaProviderViewV1 = Field(
        validation_alias=AliasChoices("persona_provider_view", "persona")
    )
    persona_spec_hash: str = Field(min_length=1)
    predecessors: tuple[PromptPredecessorTurnV1, ...] = Field(
        default=(), validation_alias=AliasChoices("predecessors", "prior_turns")
    )
    pending_question: PromptPendingQuestionV1 | None = None
    query_catalog: tuple[PromptQueryV1, ...] = Field(
        default=(), validation_alias=AliasChoices("query_catalog", "queries")
    )
    evidence_catalog: tuple[PromptEvidenceV1, ...] = Field(
        default=(), validation_alias=AliasChoices("evidence_catalog", "evidence")
    )
    transcript_hash: str = Field(min_length=1)
    receipt_hash: str = Field(min_length=1)
    output_schema_id: str = PROMPT_OUTPUT_SCHEMA_ID
    evidence_trace_schema_id: str = PROMPT_EVIDENCE_TRACE_SCHEMA_ID
    repair_feedback: PromptRepairFeedbackV1 | None = None

    @model_validator(mode="after")
    def validate_closed_request(self) -> PromptRequestV1:
        try:
            phase = resolve_round_phase(self.round_no, self.is_final_round)
        except ValueError as exc:
            raise ValueError("round phase is inconsistent") from exc
        if phase.value != self.phase:
            raise ValueError("round phase is inconsistent")
        if self.round_count is not None and self.round_no > self.round_count:
            raise ValueError("round is outside the configured schedule")
        predecessor_ids = [item.turn_id for item in self.predecessors]
        if len(predecessor_ids) != len(set(predecessor_ids)):
            raise ValueError("predecessor turn IDs must be unique")
        if tuple(item.turn_index for item in self.predecessors) != tuple(
            sorted(item.turn_index for item in self.predecessors)
        ):
            raise ValueError("predecessors must be ordered by turn index")
        if len({item.turn_index for item in self.predecessors}) != len(self.predecessors):
            raise ValueError("predecessor turn indexes must be unique")
        if any(item.round_no >= self.round_no for item in self.predecessors):
            raise ValueError("same-round or future predecessor crossed the barrier")
        if self.phase == RoundPhase.OPENING.value and self.predecessors:
            raise ValueError("opening requests cannot contain predecessor turns")
        if self.pending_question is not None:
            if self.pending_question.target_participant_id != self.participant_id:
                raise ValueError("pending question is assigned to another participant")
            if self.pending_question.source_turn_id not in predecessor_ids:
                raise ValueError("pending question source is not a visible predecessor")
            if self.pending_question.source_participant_id == self.participant_id:
                raise ValueError("pending question cannot be authored by the current participant")
        query_ids = [item.query_id for item in self.query_catalog]
        evidence_ids = [item.evidence_id for item in self.evidence_catalog]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        evidence_set = set(evidence_ids)
        for query in self.query_catalog:
            if any(evidence_id not in evidence_set for evidence_id in query.evidence_ids):
                raise ValueError("query references an unknown evidence ID")
        query_set = set(query_ids)
        for evidence in self.evidence_catalog:
            if any(query_id not in query_set for query_id in evidence.query_ids):
                raise ValueError("evidence references an unknown query ID")
        excerpts = [item.excerpt for item in self.evidence_catalog]
        if len(excerpts) != len(set(excerpts)):
            raise ValueError("evidence excerpts must be deduplicated")
        if self.output_schema_id != PROMPT_OUTPUT_SCHEMA_ID:
            raise ValueError("unsupported mutual-learning output schema")
        if self.evidence_trace_schema_id != PROMPT_EVIDENCE_TRACE_SCHEMA_ID:
            raise ValueError("unsupported EvidenceTrace schema")
        return self

    @property
    def persona(self) -> PersonaProviderViewV1:
        """Compatibility/readability alias for the single current Persona."""

        return self.persona_provider_view

    @property
    def queries(self) -> tuple[PromptQueryV1, ...]:
        return self.query_catalog

    @property
    def evidence(self) -> tuple[PromptEvidenceV1, ...]:
        return self.evidence_catalog

    def canonical_json(self) -> str:
        """Serialize exactly once with stable key order and no whitespace."""

        # Nullable control fields (for example ``repair_feedback``) are
        # omitted until they carry a value, so attempt two truly appends the
        # pointer feedback instead of sending an explicit null duplicate.
        return _canonical(self.model_dump(mode="json", exclude_none=True))

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")

    @property
    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class PromptMessageV1(PromptClosedModel):
    role: Literal["system", "user"]
    content: str = Field(min_length=1)


class ProviderPromptV1(PromptClosedModel):
    """The exact two-message request plus its pre-send budget estimate."""

    request: PromptRequestV1
    messages: tuple[PromptMessageV1, PromptMessageV1]
    budget: PromptBudgetV1
    request_hash: str
    system_rules_hash: str

    @model_validator(mode="after")
    def validate_two_messages(self) -> ProviderPromptV1:
        if tuple(message.role for message in self.messages) != ("system", "user"):
            raise ValueError("mutual-learning provider prompts require system then user messages")
        if self.messages[1].content != self.request.canonical_json():
            raise ValueError("the user message must be the canonical request JSON")
        if self.request_hash != self.request.request_hash:
            raise ValueError("provider prompt request hash is inconsistent")
        return self

    @property
    def system_message(self) -> PromptMessageV1:
        return self.messages[0]

    @property
    def user_message(self) -> PromptMessageV1:
        return self.messages[1]


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_str(value: object, *, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise PromptRequestError(f"{label} is invalid")
    return value


def _int(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise PromptRequestError(f"{label} is invalid")
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise PromptRequestError(f"{label} is invalid") from exc
    if parsed < minimum:
        raise PromptRequestError(f"{label} is invalid")
    return parsed


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _structured_dump(turn: object) -> Mapping[str, object]:
    structured = _read(turn, "structured")
    if isinstance(structured, BaseModel):
        dumped = structured.model_dump(mode="json")
        return dumped if isinstance(dumped, Mapping) else {}
    if isinstance(structured, Mapping):
        return structured
    return {}


def _question_projection(value: object) -> PromptQuestionV1:
    if value is None:
        return PromptQuestionV1()
    question_type = _read(value, "type")
    if question_type == "none" or question_type is None:
        return PromptQuestionV1()
    return PromptQuestionV1(
        type=cast(Any, question_type),
        question_id=(str(_read(value, "question_id")) if _read(value, "question_id") else None),
        source_turn_id=(
            str(_read(value, "source_turn_id")) if _read(value, "source_turn_id") else None
        ),
        source_participant_id=(
            str(_read(value, "source_participant_id"))
            if _read(value, "source_participant_id")
            else None
        ),
        target_participant_id=(
            str(_read(value, "target_participant_id"))
            if _read(value, "target_participant_id")
            else None
        ),
        text=(str(_read(value, "text")) if _read(value, "text") else None),
    )


def _claims_projection(value: object) -> tuple[PromptKeyClaimV1, ...]:
    claims: list[PromptKeyClaimV1] = []
    for item in _sequence(value):
        claims.append(
            PromptKeyClaimV1(
                claim_id=_as_str(_read(item, "claim_id"), label="claim_id"),
                claim_text=_as_str(_read(item, "claim_text"), label="claim_text"),
                claim_type=cast(Any, _as_str(_read(item, "claim_type"), label="claim_type")),
                used_evidence_ids=tuple(
                    str(identifier)
                    for identifier in _sequence(
                        _read(item, "used_evidence_ids", _read(item, "used_evidence_id", ()))
                    )
                    if identifier
                ),
            )
        )
    return tuple(claims)


def _engagement_projection(value: object) -> tuple[PromptEngagementV1, ...]:
    engagements: list[PromptEngagementV1] = []
    for item in _sequence(value):
        engagements.append(
            PromptEngagementV1(
                target_turn_id=_as_str(
                    _read(item, "target_turn_id"), label="engagement.target_turn_id"
                ),
                target_claim_id=(
                    str(_read(item, "target_claim_id")) if _read(item, "target_claim_id") else None
                ),
                relation=cast(Any, _as_str(_read(item, "relation"), label="engagement.relation")),
                faithful_summary=_as_str(
                    _read(item, "faithful_summary"), label="engagement.faithful_summary"
                ),
                response_summary=_as_str(
                    _read(item, "response_summary"), label="engagement.response_summary"
                ),
            )
        )
    return tuple(engagements)


def _disagreement_projection(value: object) -> tuple[PromptDisagreementV1, ...]:
    disagreements: list[PromptDisagreementV1] = []
    for item in _sequence(value):
        disagreements.append(
            PromptDisagreementV1(
                summary=_as_str(_read(item, "summary"), label="disagreement.summary"),
                category=cast(Any, _as_str(_read(item, "category"), label="disagreement.category")),
                claim_ids=tuple(
                    str(identifier)
                    for identifier in _sequence(_read(item, "claim_ids", ()))
                    if identifier
                ),
            )
        )
    return tuple(disagreements)


def predecessor_projection(turn: FinalReadyTurn | object) -> PromptPredecessorTurnV1:
    """Project a final-ready turn to its complete public provider view."""

    structured = _structured_dump(turn)
    speech = _read(turn, "speech", structured.get("speech"))
    turn_id = _as_str(_read(turn, "turn_id"), label="predecessor.turn_id")
    participant_id = _as_str(_read(turn, "participant_id"), label="predecessor.participant_id")
    claims = _claims_projection(structured.get("key_claims", ()))
    engagement = _engagement_projection(structured.get("engagements", ()))
    answered = structured.get("answered_question_ids", ())
    if not _sequence(answered) and structured.get("answered_question_id"):
        answered = (structured["answered_question_id"],)
    used_ids = structured.get("used_evidence_id", ())
    if not _sequence(used_ids):
        used_ids = tuple(identifier for claim in claims for identifier in claim.used_evidence_ids)
    return PromptPredecessorTurnV1(
        turn_id=turn_id,
        participant_id=participant_id,
        round_no=_int(_read(turn, "round_no"), label="predecessor.round_no", minimum=1),
        turn_index=_int(_read(turn, "turn_index"), label="predecessor.turn_index"),
        speech=_as_str(speech, label="predecessor.speech"),
        key_claims=claims,
        engagements=engagement,
        answered_question_ids=tuple(str(item) for item in _sequence(answered) if item),
        learned_from_others=tuple(
            str(item) for item in _sequence(structured.get("learned_from_others", ())) if item
        ),
        position_summary=str(structured.get("position_summary") or ""),
        position_update=(
            str(structured["position_update"])
            if structured.get("position_update") is not None
            else None
        ),
        position_update_reason=(
            str(structured["position_update_reason"])
            if structured.get("position_update_reason") is not None
            else None
        ),
        remaining_uncertainty=tuple(
            str(item) for item in _sequence(structured.get("remaining_uncertainty", ())) if item
        ),
        unresolved_issue=(
            str(structured["unresolved_issue"]) if structured.get("unresolved_issue") else None
        ),
        question=_question_projection(structured.get("question")),
        missing_information=tuple(
            str(item) for item in _sequence(structured.get("missing_information", ())) if item
        ),
        unresolved_questions=tuple(
            str(item) for item in _sequence(structured.get("unresolved_questions", ())) if item
        ),
        change_from_opening=(
            str(structured["change_from_opening"])
            if structured.get("change_from_opening") is not None
            else None
        ),
        final_consensus=tuple(
            str(item) for item in _sequence(structured.get("final_consensus", ())) if item
        ),
        final_disagreements=_disagreement_projection(structured.get("final_disagreements", ())),
        final_recommendation=(
            str(structured["final_recommendation"])
            if structured.get("final_recommendation") is not None
            else None
        ),
        used_evidence_ids=tuple(str(item) for item in _sequence(used_ids) if item),
    )


def _visible_predecessors(
    predecessors: Sequence[FinalReadyTurn | object], current_round: int
) -> tuple[FinalReadyTurn | object, ...]:
    visible: list[FinalReadyTurn | object] = []
    for item in predecessors:
        item_round = _int(_read(item, "round_no"), label="predecessor.round_no", minimum=1)
        if item_round < current_round:
            status = _read(item, "publication_status", "final_ready")
            if status not in {"final_ready", "public"}:
                raise PromptRequestError("a predecessor is not final-ready")
            visible.append(item)
    return tuple(
        sorted(
            visible,
            key=lambda item: (
                _int(_read(item, "turn_index"), label="turn_index"),
                str(_read(item, "turn_id", "")),
            ),
        )
    )


def _turn_subquery_payload(item: object, index: int) -> tuple[str, str, str, str]:
    query_kind = _read(item, "query_kind")
    query_text = _read(item, "text", _read(item, "query_text"))
    if not isinstance(query_kind, str) or not query_kind.strip():
        raise PromptRequestError("query kind is invalid")
    if not isinstance(query_text, str) or not query_text.strip():
        raise PromptRequestError("query text is invalid")
    query_text = query_text.strip()
    query_hash = _read(item, "query_hash")
    if not isinstance(query_hash, str) or not query_hash:
        query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
    query_id = _read(item, "query_id")
    if not isinstance(query_id, str) or not query_id:
        query_id = f"query-{index + 1}-{query_hash[:16]}"
    return query_id, query_kind, query_text, query_hash


def _pending_projection(
    value: PendingQuestion | PromptPendingQuestionV1 | object | None,
) -> PromptPendingQuestionV1 | None:
    if value is None:
        return None
    if isinstance(value, PromptPendingQuestionV1):
        return value
    try:
        return PromptPendingQuestionV1(
            question_id=_as_str(_read(value, "question_id"), label="pending.question_id"),
            source_turn_id=_as_str(_read(value, "source_turn_id"), label="pending.source_turn_id"),
            source_participant_id=_as_str(
                _read(value, "source_participant_id"), label="pending.source_participant_id"
            ),
            target_participant_id=_as_str(
                _read(value, "target_participant_id"), label="pending.target_participant_id"
            ),
            text=_as_str(_read(value, "text"), label="pending.text"),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, PromptRequestError):
            raise
        raise PromptRequestError("pending question is invalid") from exc


def _receipt_identity(receipt: SnapshotRetrievalReceipt) -> dict[str, object]:
    # Full identity is used only for the server-side frozen hash.  The
    # provider catalogue below receives the opaque ID and excerpt, never this
    # snapshot/source/chunk metadata.
    return {
        "evidence_id": receipt.resolved_evidence_id(),
        "snapshot_id": receipt.snapshot_id,
        "query_kind": receipt.query_kind,
        "query_hash": receipt.query_hash,
        "threshold_key": receipt.threshold_key,
        "rank": receipt.rank,
        "score": receipt.score,
        "chunk_id": receipt.chunk_id,
        "source_filename": receipt.source_filename,
        "text": receipt.text,
    }


def compute_prompt_receipt_hash(receipts: Sequence[SnapshotRetrievalReceipt]) -> str:
    return _hash([_receipt_identity(receipt) for receipt in receipts])


def compute_prompt_transcript_hash(predecessors: Sequence[FinalReadyTurn | object]) -> str:
    """Hash the same public fields as the mutual-learning generation fence.

    The wire projection is intentionally richer (for example it carries a
    predecessor's question identity), but the persisted transcript fence is
    shared with ``compute_mutual_transcript_hash`` so an adapter can pass its
    already-fenced hash without creating a second history identity.
    """

    projected = tuple(predecessor_projection(item) for item in predecessors)
    payload = []
    for item in sorted(
        projected, key=lambda value: (value.round_no, value.turn_index, value.turn_id)
    ):
        payload.append(
            {
                "turn_id": item.turn_id,
                "participant_id": item.participant_id,
                "round_no": item.round_no,
                "turn_index": item.turn_index,
                "speech": item.speech,
                "key_claims": [claim.model_dump(mode="json") for claim in item.key_claims],
                "engagements": [
                    engagement.model_dump(mode="json") for engagement in item.engagements
                ],
                "answered_question_ids": list(item.answered_question_ids),
                "learned_from_others": list(item.learned_from_others),
                "position_summary": item.position_summary,
                "position_update": item.position_update or "unchanged",
                "position_update_reason": item.position_update_reason,
                "remaining_uncertainty": list(item.remaining_uncertainty),
                "unresolved_issue": item.unresolved_issue,
                "question": {
                    "type": item.question.type,
                    "target_participant_id": item.question.target_participant_id,
                    "text": item.question.text,
                },
                "used_evidence_id": list(item.used_evidence_ids),
                "missing_information": list(item.missing_information),
                "unresolved_questions": list(item.unresolved_questions),
                "change_from_opening": item.change_from_opening,
                "final_consensus": list(item.final_consensus),
                "final_disagreements": [
                    disagreement.model_dump(mode="json")
                    for disagreement in item.final_disagreements
                ],
                "final_recommendation": item.final_recommendation,
            }
        )
    return _hash(payload)


def compute_prompt_rule_hash(rule_set_id: str, rules: Sequence[str]) -> str:
    return _hash({"rule_set_id": rule_set_id, "rules": tuple(rules)})


def compute_prompt_persona_hash(persona: PersonaSpecV1 | PersonaProviderViewV1) -> str:
    if isinstance(persona, PersonaSpecV1):
        return persona_spec_hash(persona)
    return _hash(persona.model_dump(mode="json"))


def confirmed_persona_provider_view(
    persona_spec_json: str,
    *,
    expected_persona_spec_hash: str | None = None,
) -> tuple[PersonaProviderViewV1, str]:
    """Parse one persisted confirmed Persona without accepting raw fallback.

    The persistence adapter supplies the canonical ``persona_spec_json`` and
    its stored hash.  A missing/invalid/mismatched value fails closed; callers
    must not pass ``AgentVersion.agent_md`` as a substitute.
    """

    if not isinstance(persona_spec_json, str) or not persona_spec_json.strip():
        raise PromptRequestError(
            "a confirmed structured Persona is required",
            code="persona_provider_view_required",
        )
    try:
        decoded = json.loads(persona_spec_json)
        spec = PersonaSpecV1.model_validate(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PromptRequestError(
            "the persisted Persona is invalid", code="persona_invalid"
        ) from exc
    canonical = _canonical(spec.model_dump(mode="json"))
    if canonical != persona_spec_json:
        raise PromptRequestError(
            "the persisted Persona is not canonical", code="persona_hash_changed"
        )
    resolved_hash = persona_spec_hash(spec)
    if expected_persona_spec_hash is not None and expected_persona_spec_hash != resolved_hash:
        raise PromptRequestError("the persisted Persona hash changed", code="persona_hash_changed")
    try:
        return provider_view(spec), resolved_hash
    except ValueError as exc:
        raise PromptRequestError("the Persona cannot be exported", code="persona_invalid") from exc


def render_prompt_system_message(
    *,
    rule_set_id: str = MUTUAL_LEARNING_RULE_SET_ID,
    rule_set_hash: str | None = None,
    rules: Sequence[str] = MUTUAL_LEARNING_PLATFORM_RULES,
) -> str:
    """Render one versioned system message; rules prose appears exactly once."""

    frozen_rules = tuple(_as_str(item, label="platform rule") for item in rules)
    resolved_hash = rule_set_hash or compute_prompt_rule_hash(rule_set_id, frozen_rules)
    return "\n".join(
        (
            PROMPT_SYSTEM_VERSION,
            f"rule_set_id={rule_set_id}",
            f"rule_set_hash={resolved_hash}",
            "PLATFORM_PRIORITY_RULES_BEGIN",
            *frozen_rules,
            "PLATFORM_PRIORITY_RULES_END",
        )
    )


def _resolve_context_values(
    context: GenerationContext | None,
    *,
    debate_id: str | None,
    topic: str | None,
    turn_plan: object | None,
    participant: object | None,
    predecessors: Sequence[FinalReadyTurn | object],
    pending_question: object | None,
) -> tuple[str, str, object, object, Sequence[FinalReadyTurn | object], object | None]:
    if context is not None:
        debate_id = debate_id or context.debate_id
        topic = topic or context.topic
        turn_plan = turn_plan or context.turn
        participant = participant or context.participant
        if not predecessors:
            predecessors = context.predecessors
        if pending_question is None:
            pending_question = context.effective_pending_question
    if debate_id is None or topic is None or turn_plan is None or participant is None:
        raise PromptRequestError(
            "debate, topic, turn plan and participant are required",
            code="prompt_request_context_missing",
        )
    return debate_id, topic, turn_plan, participant, predecessors, pending_question


def build_prompt_request(
    context: GenerationContext | None = None,
    *,
    debate_id: str | None = None,
    topic: str | None = None,
    turn_plan: object | None = None,
    plan: object | None = None,
    participant: object | None = None,
    persona: PersonaSpecV1 | PersonaProviderViewV1 | None = None,
    predecessors: Sequence[FinalReadyTurn | object] = (),
    receipts: Sequence[SnapshotRetrievalReceipt] = (),
    queries: Sequence[object] | None = None,
    query_catalog: Sequence[object] | None = None,
    pending_question: PendingQuestion | PromptPendingQuestionV1 | object | None = None,
    round_count: int | None = None,
    rule_set_id: str = MUTUAL_LEARNING_RULE_SET_ID,
    rule_set_hash: str | None = None,
    persona_spec_hash_value: str | None = None,
    persona_hash: str | None = None,
    transcript_hash: str | None = None,
    receipt_hash: str | None = None,
    rules: Sequence[str] = MUTUAL_LEARNING_PLATFORM_RULES,
    repair_feedback: PromptRepairFeedbackV1 | Mapping[str, object] | None = None,
) -> PromptRequestV1:
    """Build a closed logical request without any provider or retrieval call."""

    if turn_plan is None:
        turn_plan = plan
    (
        debate_id,
        topic,
        turn_plan,
        participant,
        predecessors,
        pending_question,
    ) = _resolve_context_values(
        context,
        debate_id=debate_id,
        topic=topic,
        turn_plan=turn_plan,
        participant=participant,
        predecessors=predecessors,
        pending_question=pending_question,
    )
    if rule_set_id != MUTUAL_LEARNING_RULE_SET_ID:
        raise PromptRequestError("unsupported mutual-learning RuleSet", code="rule_set_unavailable")
    if persona is None:
        participant_persona = _read(participant, "persona")
        if isinstance(participant_persona, (PersonaSpecV1, PersonaProviderViewV1)):
            persona = participant_persona
        else:
            raise PromptRequestError(
                "a confirmed PersonaProviderView is required; raw AGENT.md is not accepted",
                code="persona_provider_view_required",
            )
    if isinstance(persona, PersonaSpecV1):
        try:
            current_persona = provider_view(persona)
        except ValueError as exc:
            raise PromptRequestError(
                "the current Persona cannot be exported", code="persona_invalid"
            ) from exc
        computed_persona_hash = persona_spec_hash(persona)
    elif isinstance(persona, PersonaProviderViewV1):
        current_persona = persona
        computed_persona_hash = compute_prompt_persona_hash(persona)
    else:
        raise PromptRequestError("PersonaProviderView is invalid", code="persona_invalid")

    plan_round = _int(_read(turn_plan, "round_no"), label="turn_plan.round_no", minimum=1)
    plan_final = _read(turn_plan, "is_final_round")
    if not isinstance(plan_final, bool):
        raise PromptRequestError("turn plan final marker is invalid")
    try:
        phase = resolve_round_phase(plan_round, plan_final)
    except ValueError as exc:
        raise PromptRequestError("turn plan phase is invalid") from exc
    declared_phase = _as_str(_read(turn_plan, "phase"), label="turn_plan.phase")
    if phase.value != declared_phase:
        raise PromptRequestError("turn plan phase is inconsistent")
    visible = _visible_predecessors(predecessors, plan_round)
    predecessor_models = tuple(predecessor_projection(item) for item in visible)
    predecessor_ids = tuple(item.turn_id for item in predecessor_models)
    planned_ids = _read(turn_plan, "predecessor_turn_ids", ())
    if (
        _sequence(planned_ids)
        and tuple(str(item) for item in _sequence(planned_ids)) != predecessor_ids
    ):
        raise PromptRequestError("visible predecessors do not match the frozen turn plan")
    resolved_round_count = round_count
    if resolved_round_count is None:
        raw_count = _read(turn_plan, "round_count")
        if isinstance(raw_count, int) and not isinstance(raw_count, bool):
            resolved_round_count = raw_count
    if resolved_round_count is not None:
        resolved_round_count = _int(resolved_round_count, label="round_count", minimum=2)
        if plan_round > resolved_round_count:
            raise PromptRequestError("turn is outside the configured round count")

    typed_receipts = tuple(receipts)
    participant_snapshot_id = _read(participant, "snapshot_id")
    if not isinstance(participant_snapshot_id, str) or not participant_snapshot_id:
        raise PromptRequestError("participant snapshot is unavailable", code="snapshot_unavailable")
    for receipt in typed_receipts:
        if receipt.snapshot_id != participant_snapshot_id:
            raise PromptRequestError(
                "evidence belongs to another participant snapshot",
                code="cross_snapshot_evidence",
            )
    frozen_rules = tuple(_as_str(item, label="platform rule") for item in rules)
    resolved_rule_hash = rule_set_hash or compute_prompt_rule_hash(rule_set_id, frozen_rules)
    stored_persona_hash = _read(participant, "persona_spec_hash")
    resolved_persona_hash = (
        persona_spec_hash_value
        or persona_hash
        or (str(stored_persona_hash) if stored_persona_hash else None)
        or computed_persona_hash
    )
    if not isinstance(resolved_persona_hash, str) or not resolved_persona_hash.strip():
        raise PromptRequestError("persona hash is unavailable", code="persona_hash_missing")
    if isinstance(persona, PersonaSpecV1) and resolved_persona_hash != computed_persona_hash:
        raise PromptRequestError(
            "persona hash does not match the structured Persona", code="persona_hash_changed"
        )
    computed_transcript = compute_prompt_transcript_hash(visible)
    if transcript_hash is not None and transcript_hash != computed_transcript:
        raise PromptRequestError(
            "transcript hash does not match visible predecessors", code="transcript_hash_changed"
        )
    computed_receipt = compute_prompt_receipt_hash(typed_receipts)
    if receipt_hash is not None and receipt_hash != computed_receipt:
        raise PromptRequestError(
            "receipt hash does not match supplied receipts", code="receipt_hash_changed"
        )

    pending = _pending_projection(pending_question)
    if pending is not None and pending.target_participant_id != str(
        _read(participant, "participant_id")
    ):
        raise PromptRequestError("pending question is assigned to another participant")

    query_items = query_catalog if query_catalog is not None else queries
    if query_items is None and context is not None:
        from .retrieval import build_turn_subqueries

        query_items = build_turn_subqueries(context, pending_question=pending_question)  # type: ignore[arg-type]
    if query_items is None:
        query_items = ()
    query_models: list[PromptQueryV1] = []
    query_by_hash: dict[str, PromptQueryV1] = {}
    for index, item in enumerate(query_items):
        if isinstance(item, PromptQueryV1):
            query = item
        else:
            query_id, query_kind, query_text, query_hash_value = _turn_subquery_payload(item, index)
            query = PromptQueryV1(
                query_id=query_id,
                query_kind=query_kind,
                query_text=query_text,
                query_hash=query_hash_value,
            )
        duplicate_key = (query.query_kind, query.query_hash, query.query_text)
        if any(
            (existing.query_kind, existing.query_hash, existing.query_text) == duplicate_key
            for existing in query_models
        ):
            continue
        query_models.append(query)
        query_by_hash.setdefault(query.query_hash, query)

    # Deduplicate by exact evidence excerpt as well as evidence ID.  If two
    # queries retrieved the same text under different opaque IDs, the first
    # server-assigned ID remains canonical and all query links are rewritten.
    evidence_models: list[PromptEvidenceV1] = []
    evidence_by_id: dict[str, PromptEvidenceV1] = {}
    evidence_by_excerpt: dict[str, PromptEvidenceV1] = {}
    receipt_id_alias: dict[str, str] = {}
    for receipt in typed_receipts:
        evidence_id = receipt.resolved_evidence_id()
        existing_id = evidence_by_id.get(evidence_id)
        if existing_id is not None:
            if existing_id.excerpt != receipt.text:
                raise PromptRequestError("duplicate evidence ID has conflicting text")
            receipt_id_alias[evidence_id] = existing_id.evidence_id
            continue
        existing_excerpt = evidence_by_excerpt.get(receipt.text)
        if existing_excerpt is not None:
            receipt_id_alias[evidence_id] = existing_excerpt.evidence_id
            continue
        evidence = PromptEvidenceV1(evidence_id=evidence_id, excerpt=receipt.text)
        evidence_models.append(evidence)
        evidence_by_id[evidence_id] = evidence
        evidence_by_excerpt[receipt.text] = evidence
        receipt_id_alias[evidence_id] = evidence_id
    query_links: dict[str, list[str]] = {query.query_id: [] for query in query_models}
    for receipt in typed_receipts:
        canonical_id = receipt_id_alias[receipt.resolved_evidence_id()]
        matching = query_by_hash.get(receipt.query_hash)
        if matching is not None and canonical_id not in query_links[matching.query_id]:
            query_links[matching.query_id].append(canonical_id)
    for index, query in enumerate(query_models):
        linked = list(query.evidence_ids)
        linked.extend(query_links.get(query.query_id, ()))
        remapped = tuple(
            dict.fromkeys(receipt_id_alias.get(identifier, identifier) for identifier in linked)
        )
        query_models[index] = query.model_copy(update={"evidence_ids": remapped})
    evidence_query_ids: dict[str, list[str]] = {item.evidence_id: [] for item in evidence_models}
    for query in query_models:
        for evidence_id in query.evidence_ids:
            if evidence_id not in evidence_query_ids:
                raise PromptRequestError("query references unknown evidence")
            evidence_query_ids[evidence_id].append(query.query_id)
    evidence_models = [
        item.model_copy(
            update={"query_ids": tuple(dict.fromkeys(evidence_query_ids[item.evidence_id]))}
        )
        for item in evidence_models
    ]
    try:
        request = PromptRequestV1(
            debate_id=_as_str(debate_id, label="debate_id"),
            turn_id=_as_str(_read(turn_plan, "turn_id"), label="turn_plan.turn_id"),
            rule_set_id=rule_set_id,
            rule_set_hash=_as_str(resolved_rule_hash, label="rule_set_hash"),
            phase=cast(Any, phase.value),
            round_no=plan_round,
            round_count=resolved_round_count,
            turn_index=_int(_read(turn_plan, "turn_index"), label="turn_plan.turn_index"),
            participant_id=_as_str(_read(participant, "participant_id"), label="participant_id"),
            participant_slot=_as_str(_read(turn_plan, "slot"), label="participant_slot"),
            participant_order_index=_int(
                _read(turn_plan, "order_index"), label="participant_order_index"
            ),
            next_participant_id=(
                str(_read(turn_plan, "next_participant_id"))
                if _read(turn_plan, "next_participant_id")
                else None
            ),
            is_final_round=plan_final,
            # Every expert's final-integration turn is semantically final;
            # ``TurnPlan.is_final`` only marks the last scheduled playback
            # row and must not make earlier final-integration experts look
            # like exchange turns to a Provider.
            is_final_turn=phase is RoundPhase.FINAL_INTEGRATION,
            topic=_as_str(topic, label="topic"),
            assigned_stance=(
                str(_read(participant, "current_stance") or _read(participant, "initial_stance"))
                if (_read(participant, "current_stance") or _read(participant, "initial_stance"))
                else None
            ),
            persona_provider_view=current_persona,
            persona_spec_hash=resolved_persona_hash,
            predecessors=predecessor_models,
            pending_question=pending,
            query_catalog=tuple(query_models),
            evidence_catalog=tuple(evidence_models),
            transcript_hash=transcript_hash or computed_transcript,
            receipt_hash=receipt_hash or computed_receipt,
            repair_feedback=(
                repair_feedback
                if isinstance(repair_feedback, PromptRepairFeedbackV1)
                else (
                    PromptRepairFeedbackV1.model_validate(repair_feedback)
                    if repair_feedback is not None
                    else None
                )
            ),
        )
    except PromptRequestError:
        raise
    except ValueError as exc:
        raise PromptRequestError("the closed prompt request is invalid") from exc
    return request


def build_provider_prompt(
    context: GenerationContext | None = None,
    *,
    token_counter: TokenCounterPort | object | None = None,
    requested_output_tokens: int = MAX_OUTPUT_TOKENS,
    rules: Sequence[str] | None = None,
    **kwargs: Any,
) -> ProviderPromptV1:
    """Build two provider messages and run the zero-I/O budget preflight."""

    if rules is None:
        # The Debate states its own language; only a caller that has no
        # context to read falls back to the English tuple.
        rules = (
            mutual_learning_platform_rules(context.output_language)
            if context is not None
            else MUTUAL_LEARNING_PLATFORM_RULES
        )
    request = build_prompt_request(context, rules=rules, **kwargs)
    system = render_prompt_system_message(
        rule_set_id=request.rule_set_id,
        rule_set_hash=request.rule_set_hash,
        rules=rules,
    )
    user = request.canonical_json()
    budget = preflight_prompt_budget(
        (system, user),
        request_bytes=len(user.encode("utf-8")),
        requested_output_tokens=requested_output_tokens,
        token_counter=token_counter,
    )
    return ProviderPromptV1(
        request=request,
        messages=(
            PromptMessageV1(role="system", content=system),
            PromptMessageV1(role="user", content=user),
        ),
        budget=budget,
        request_hash=request.request_hash,
        system_rules_hash=_hash(tuple(rules)),
    )


def build_provider_prompt_from_mutual_input(
    prompt: MutualLearningPromptInput,
    *,
    persona: PersonaSpecV1 | PersonaProviderViewV1,
    token_counter: TokenCounterPort | object | None = None,
    requested_output_tokens: int = MAX_OUTPUT_TOKENS,
    rules: Sequence[str] | None = None,
    **kwargs: Any,
) -> ProviderPromptV1:
    """Adapt the existing pure mutual input to the new two-message seam.

    The input object may still carry raw/private fields for legacy Mock
    compatibility; this adapter deliberately reads only its frozen public
    predecessor/receipt values and the supplied confirmed Persona view.
    """

    context = GenerationContext(
        debate_id=prompt.debate_id,
        topic=prompt.topic,
        turn=prompt.turn_plan,
        participant=prompt.participant,
        participants=prompt.participants,
        predecessors=prompt.predecessors,
        pending_question=prompt.pending_question,
        output_language=prompt.output_language,
    )
    # The rules the provider is actually sent must state the language this
    # Debate chose. Defaulting to the English tuple here meant a Chinese
    # debate asked the model, in English, for English -- and then rejected the
    # English it got back.
    if rules is None:
        rules = mutual_learning_platform_rules(prompt.output_language)
    return build_provider_prompt(
        context,
        persona=persona,
        receipts=prompt.receipts,
        token_counter=token_counter,
        requested_output_tokens=requested_output_tokens,
        rules=rules,
        **kwargs,
    )


class PromptRequestBuilder:
    """Reusable pure builder configured with one rules/tokenizer snapshot."""

    def __init__(
        self,
        *,
        rules: Sequence[str] = MUTUAL_LEARNING_PLATFORM_RULES,
        token_counter: TokenCounterPort | object | None = None,
        requested_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        self.rules = tuple(rules)
        self.token_counter = token_counter
        self.requested_output_tokens = requested_output_tokens

    def build_request(
        self, context: GenerationContext | None = None, **kwargs: Any
    ) -> PromptRequestV1:
        return build_prompt_request(context, rules=self.rules, **kwargs)

    def build(self, context: GenerationContext | None = None, **kwargs: Any) -> ProviderPromptV1:
        return build_provider_prompt(
            context,
            token_counter=self.token_counter,
            requested_output_tokens=self.requested_output_tokens,
            rules=self.rules,
            **kwargs,
        )


def canonical_prompt_json(request: PromptRequestV1) -> str:
    return request.canonical_json()


def build_prompt_request_and_budget(*args: Any, **kwargs: Any) -> ProviderPromptV1:
    return build_provider_prompt(*args, **kwargs)


build_prompt_messages = build_provider_prompt
render_prompt = build_provider_prompt


# Descriptive aliases for integration code.
PromptMessage = PromptMessageV1
PromptRequest = PromptRequestV1
PromptBudgetRequest = ProviderPromptV1
EngagementProjection = PromptEngagementV1
KeyClaimProjection = PromptKeyClaimV1


__all__ = [
    "EngagementProjection",
    "KeyClaimProjection",
    "PROMPT_EVIDENCE_TRACE_SCHEMA_ID",
    "PROMPT_OUTPUT_SCHEMA_ID",
    "PROMPT_REQUEST_VERSION",
    "PROMPT_SYSTEM_VERSION",
    "PromptDisagreementV1",
    "PromptEngagementV1",
    "PromptEvidenceV1",
    "PromptKeyClaimV1",
    "PromptMessage",
    "PromptMessageV1",
    "PromptPendingQuestionV1",
    "PromptPredecessorTurnV1",
    "PromptQuestionV1",
    "PromptRepairFeedbackV1",
    "PromptRequest",
    "PromptRequestError",
    "PromptRequestV1",
    "PromptRequestBuilder",
    "PromptBudgetRequest",
    "PromptQueryV1",
    "ProviderPromptV1",
    "build_prompt_request",
    "build_prompt_request_and_budget",
    "build_prompt_messages",
    "build_provider_prompt",
    "build_provider_prompt_from_mutual_input",
    "canonical_prompt_json",
    "compute_prompt_persona_hash",
    "compute_prompt_receipt_hash",
    "compute_prompt_rule_hash",
    "compute_prompt_transcript_hash",
    "confirmed_persona_provider_view",
    "predecessor_projection",
    "render_prompt",
    "render_prompt_system_message",
]
