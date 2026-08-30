"""Provider-neutral data contracts for M11 turn generation.

The generation package intentionally has no dependency on the Wave 2 ORM.  A
setup repository can adapt its rows to these small immutable objects and a
playback worker can persist the resulting :class:`FinalReadyTurn` without
giving a provider access to database models.  The same boundary is useful in
tests: every hash and validation decision can be exercised without a running
FastAPI application or an external key.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.agents.persona import PersonaProviderViewV1, PersonaSpecV1

if TYPE_CHECKING:
    from .policy import TurnPlan


StanceMode = Literal["assigned", "open"]
Stance = Literal["support", "oppose", "neutral"]
PositionUpdate = Literal["unchanged", "refined", "partial_concession", "reframed", "switched"]
QuestionType = Literal["agent", "audience_reflection", "none"]
RetrievalStatus = Literal["matched", "no_match"]
GroundingMode = Literal["rag_grounded", "mixed", "general_reasoning"]

# These literals are deliberately separate from the historical v1/v2
# ``PositionUpdate`` and ``QuestionType`` values.  A legacy turn is parsed by
# its legacy RuleSet and therefore never has to reinterpret one of these new
# values.
EngagementRelation = Literal["agree", "extend", "qualify", "challenge", "reconcile"]
ClaimType = Literal["factual", "interpretation", "value_judgement", "proposal"]
MutualPositionUpdate = Literal[
    "unchanged",
    "clarified",
    "extended",
    "qualified",
    "partially_revised",
    "substantially_revised",
]
DisagreementCategory = Literal[
    "different_persona_or_framework",
    "different_evidence",
    "evidence_conflict",
    "insufficient_information",
    "value_tradeoff",
]
EvidenceTraceClaimType = Literal["factual", "background", "value_judgement", "proposal"]
EvidenceTraceSupportMode = Literal["direct", "contextual", "general_reasoning", "no_match"]


class TurnValidationError(ValueError):
    """A closed structured-result or evidence contract was violated."""

    def __init__(self, message: str, *, code: str = "turn_generation_failed") -> None:
        super().__init__(message)
        self.code = code


class GenerationProviderError(RuntimeError):
    """Provider-neutral technical failure eligible for one shared retry."""

    code = "provider_unavailable"


class GenerationFailed(RuntimeError):
    """Generation exhausted its shared two-attempt repair budget."""

    code = "turn_generation_failed"

    def __init__(self, message: str, *, attempt: int = 2) -> None:
        super().__init__(message)
        self.attempt = attempt


class GenerationDiscarded(RuntimeError):
    """A late provider result failed the current turn/debate fence."""

    code = "generation_result_discarded"


class TurnQuestion(BaseModel):
    """The only question shape a turn provider may return."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: QuestionType = "none"
    target_participant_id: str | None = None
    text: str | None = None


class StructuredTurnResult(BaseModel):
    """Closed provider output for one speech turn.

    Retrieval and grounding status are deliberately absent.  The server
    derives those values from the typed receipts returned by its own retriever
    and from ``used_evidence_id``.  A provider therefore cannot forge a source
    filename, select a chunk from another snapshot, or claim ``rag_grounded``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    speech: str = Field(min_length=1)
    answered_question_id: str | None = None
    rebuttal_target_turn_id: str | None = None
    rebuttal_summary: str = ""
    new_argument_summary: str = ""
    turn_summary: str = ""
    position_summary: str = ""
    position_update: PositionUpdate = "unchanged"
    new_stance: Stance | None = None
    position_update_reason: str | None = None
    used_evidence_id: list[str] = Field(default_factory=list)
    question: TurnQuestion = Field(default_factory=TurnQuestion)

    @classmethod
    def from_provider(
        cls, value: StructuredTurnResult | Mapping[str, object]
    ) -> StructuredTurnResult:
        """Parse a provider value while preserving the closed-object rule."""

        if isinstance(value, cls):
            return value
        try:
            return cls.model_validate(value)
        except Exception as exc:
            raise TurnValidationError("The LLM returned an invalid closed turn object.") from exc


class EngagementV1(BaseModel):
    """A public, claim-level response to an earlier expert turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_turn_id: str = Field(min_length=1)
    target_claim_id: str | None = Field(default=None, min_length=1)
    relation: EngagementRelation
    faithful_summary: str = Field(min_length=1)
    response_summary: str = Field(min_length=1)


class KeyClaimV1(BaseModel):
    """A structured claim whose evidence lineage is server-checked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: ClaimType
    used_evidence_ids: list[str] = Field(default_factory=list)


class EvidenceTraceClaimV1(BaseModel):
    """Exact speech claim input used to derive server-owned trace rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_text: str = Field(min_length=1)
    claim_type: EvidenceTraceClaimType
    used_evidence_ids: list[str] = Field(default_factory=list)
    support_mode: EvidenceTraceSupportMode | None = None


class MutualLearningDisagreementV1(BaseModel):
    """A preserved disagreement and its reason category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    category: DisagreementCategory
    claim_ids: list[str] = Field(default_factory=list)


# ``FinalDisagreementV1`` is a descriptive alias used by public adapters.
FinalDisagreementV1 = MutualLearningDisagreementV1
Engagement = EngagementV1
KeyClaim = KeyClaimV1


class MutualLearningTurnResultV1(BaseModel):
    """Versioned structured output for one mutual-learning turn.

    Final-only fields remain nullable/empty at the DTO boundary so persisted
    JSON can be read by generic tooling.  ``MutualLearningValidator`` closes
    those fields according to the resolved phase.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    speech: str = Field(min_length=1)
    key_claims: list[KeyClaimV1] = Field(default_factory=list)
    evidence_trace_claims: list[EvidenceTraceClaimV1] = Field(default_factory=list)
    engagements: list[EngagementV1] = Field(default_factory=list)
    answered_question_ids: list[str] = Field(default_factory=list)
    learned_from_others: list[str] = Field(default_factory=list)
    position_summary: str = ""
    position_update: MutualPositionUpdate = "unchanged"
    position_update_reason: str | None = None
    remaining_uncertainty: list[str] = Field(default_factory=list)
    unresolved_issue: str | None = None
    question: TurnQuestion = Field(default_factory=TurnQuestion)
    # ``used_evidence_id`` is a compatibility projection used by the frozen
    # turn/source persistence seam.  Claim-level IDs remain authoritative for
    # the new protocol and the validator requires both projections to agree
    # when the top-level list is supplied.
    used_evidence_id: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    unresolved_question_ids: list[str] = Field(default_factory=list)
    change_from_opening: str | None = None
    final_consensus: list[str] = Field(default_factory=list)
    final_disagreements: list[MutualLearningDisagreementV1] = Field(default_factory=list)
    final_recommendation: str | None = None

    @classmethod
    def from_provider(
        cls,
        value: MutualLearningTurnResultV1 | Mapping[str, object],
    ) -> MutualLearningTurnResultV1:
        if isinstance(value, cls):
            return value
        try:
            return cls.model_validate(value)
        except Exception as exc:
            raise TurnValidationError(
                "The LLM returned an invalid mutual-learning turn object."
            ) from exc

    @property
    def used_evidence_ids(self) -> tuple[str, ...]:
        """Return the de-duplicated claim evidence projection in order."""

        if self.used_evidence_id:
            return tuple(dict.fromkeys(self.used_evidence_id))
        values: list[str] = []
        for claim in self.key_claims:
            values.extend(claim.used_evidence_ids)
        return tuple(dict.fromkeys(values))


class MutualLearningPositionChangeV1(BaseModel):
    """Public synthesis projection of one expert's opening-to-final change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    participant_id: str = Field(min_length=1)
    change: str = Field(min_length=1)


class MutualLearningEvidenceConflictV1(BaseModel):
    """Public synthesis projection for an evidence conflict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)


class MutualLearningSynthesisV1(BaseModel):
    """Deterministic public synthesis derived only from final-ready turns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direct_answer: str = Field(min_length=1)
    consensus: list[str] = Field(default_factory=list)
    complementary_views: list[str] = Field(default_factory=list)
    remaining_disagreements: list[MutualLearningDisagreementV1] = Field(default_factory=list)
    position_changes: list[MutualLearningPositionChangeV1] = Field(default_factory=list)
    evidence_conflicts: list[MutualLearningEvidenceConflictV1] = Field(default_factory=list)
    remaining_uncertainty: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)


MutualLearningTurnResult = MutualLearningTurnResultV1
MutualLearningSynthesis = MutualLearningSynthesisV1


_SAFE_FILENAME_RE = re.compile(r"^[^/\\\x00\x00-\x1f\x7f]+$")


@dataclass(frozen=True, slots=True)
class SnapshotRetrievalReceipt:
    """A server-authored, typed retrieval result.

    ``evidence_id`` is intentionally optional for ergonomic test fixtures.  A
    missing ID is resolved to a stable digest by :meth:`resolved_evidence_id`;
    the retriever always materialises it before passing a receipt to an LLM.
    The remaining fields mirror the frozen G0 receipt contract exactly.
    """

    snapshot_id: str
    query_kind: str
    query_hash: str
    threshold_key: Literal["strict", "relaxed"]
    rank: int
    score: float
    chunk_id: str
    source_filename: str
    text: str
    evidence_id: str = ""
    source_document_id: str | None = None
    source_start_offset: int | None = None
    source_end_offset: int | None = None
    excerpt: str | None = None
    query_id: str | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.query_kind or not self.query_hash:
            raise ValueError("retrieval receipt identity is required")
        if self.threshold_key not in {"strict", "relaxed"}:
            raise ValueError("retrieval threshold must be strict or relaxed")
        if self.rank < 1:
            raise ValueError("retrieval rank must be positive")
        if not math.isfinite(self.score):
            raise ValueError("retrieval score must be finite")
        if not self.chunk_id or not self.text.strip():
            raise ValueError("retrieval chunk identity and text are required")
        if not _SAFE_FILENAME_RE.match(self.source_filename):
            raise ValueError("retrieval source filename is unsafe")
        if not self.evidence_id:
            raw = "\x1f".join(str(item) for item in self.canonical_identity())
            object.__setattr__(
                self,
                "evidence_id",
                "evidence-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32],
            )
        if (self.source_start_offset is None) != (self.source_end_offset is None):
            raise ValueError("source document offsets must be supplied as one complete tuple")
        if self.source_start_offset is not None and self.source_document_id is None:
            raise ValueError("source document id is required with source document offsets")
        if self.source_start_offset is not None and (
            self.source_start_offset < 0
            or self.source_end_offset is None
            or self.source_end_offset <= self.source_start_offset
        ):
            raise ValueError("source document offsets must be a non-empty half-open span")

    def identity_key(self) -> tuple[str, str]:
        return self.snapshot_id, self.chunk_id

    def canonical_identity(self) -> tuple[str, str, str, str, int, float, str, str, str]:
        return (
            self.snapshot_id,
            self.query_kind,
            self.query_hash,
            self.threshold_key,
            self.rank,
            self.score,
            self.chunk_id,
            self.source_filename,
            self.text,
        )

    def resolved_evidence_id(self) -> str:
        if self.evidence_id:
            return self.evidence_id
        raw = "\x1f".join(str(item) for item in self.canonical_identity())
        return "evidence-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def id(self) -> str:
        """Convenience alias used by adapters that call receipts ``id``."""

        return self.resolved_evidence_id()


# ``SelectedEvidence`` is a descriptive alias kept separate from the public
# source DTO.  It prevents callers from accidentally treating an unused
# retrieval result as a citation.
SelectedEvidence = SnapshotRetrievalReceipt


@dataclass(frozen=True, slots=True)
class PublicSource:
    """A provider-neutral source projection for a persisted public turn."""

    source_filename: str
    chunk_id: str
    evidence_id: str
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class ParticipantContext:
    """Frozen participant/persona input consumed by one generation call."""

    participant_id: str
    agent_id: str
    agent_name: str
    slot: str
    order_index: int
    snapshot_id: str
    agent_md: str = ""
    stance_mode: StanceMode = "open"
    initial_stance: Stance | None = None
    current_stance: Stance | None = None
    initial_position_summary: str = ""
    current_position_summary: str = ""
    teacher_note: str = ""
    # New W4-PROMPT callers provide the confirmed structured Persona here.
    # Legacy contexts may leave it unset; the legacy RuleSet path never reads
    # this field and therefore keeps its historical raw-input semantics.
    persona: PersonaSpecV1 | PersonaProviderViewV1 | None = None
    persona_spec_hash: str | None = None

    def __post_init__(self) -> None:
        if self.stance_mode == "assigned" and self.initial_stance is None:
            raise ValueError("assigned participants need an initial stance")
        if self.stance_mode == "open" and self.initial_stance is not None:
            raise ValueError("open participants cannot carry an assigned stance")
        if self.stance_mode == "open" and self.current_stance is not None:
            raise ValueError("open participants cannot synthesize a stance enum")

    @property
    def effective_position_summary(self) -> str:
        return self.current_position_summary or self.initial_position_summary


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """A question from a final-ready predecessor awaiting this participant."""

    question_id: str
    source_turn_id: str
    source_participant_id: str
    target_participant_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.question_id or not self.source_turn_id or not self.text.strip():
            raise ValueError("pending question fields are required")
        if self.target_participant_id == self.source_participant_id:
            raise ValueError("a pending question cannot target its author")


@dataclass(frozen=True, slots=True)
class TurnPromptInput:
    """Immutable prompt input and final-ready predecessor fence."""

    debate_id: str
    topic: str
    rule_set_id: str
    phase: str
    turn_plan: TurnPlan
    participant: ParticipantContext
    participants: tuple[ParticipantContext, ...]
    agent_md: str
    stance_mode: StanceMode
    assigned_stance: Stance | None
    teacher_note: str
    current_position_summary: str
    predecessors: tuple[FinalReadyTurn, ...]
    predecessor_turn_ids: tuple[str, ...]
    cutoff_turn_index: int
    transcript_hash: str
    receipts: tuple[SnapshotRetrievalReceipt, ...] = ()
    pending_question: PendingQuestion | None = None

    def __post_init__(self) -> None:
        if self.participant.snapshot_id == "":
            raise ValueError("participant snapshot is required")
        if self.assigned_stance is not None and self.stance_mode != "assigned":
            raise ValueError("open prompt cannot carry an assigned stance")
        if self.stance_mode == "assigned" and self.assigned_stance is None:
            raise ValueError("assigned prompt requires a stance")
        if self.predecessor_turn_ids != tuple(item.turn_id for item in self.predecessors):
            raise ValueError("predecessor_turn_ids must match the final-ready prefix")
        if self.cutoff_turn_index != self.turn_plan.turn_index - 1:
            raise ValueError("cutoff_turn_index must be the immediate predecessor index")


@dataclass(frozen=True, slots=True)
class MutualLearningPromptInput:
    """Prompt boundary with a completed-round visibility fence.

    This is intentionally a separate DTO from :class:`TurnPromptInput`: the
    latter's lower-index prefix is part of the frozen legacy contract, while
    mutual learning hashes and carries only prior-round public turns.
    """

    debate_id: str
    topic: str
    rule_set_id: str
    phase: str
    turn_plan: TurnPlan
    participant: ParticipantContext
    participants: tuple[ParticipantContext, ...]
    agent_md: str
    stance_mode: StanceMode
    assigned_stance: Stance | None
    teacher_note: str
    current_position_summary: str
    predecessors: tuple[FinalReadyTurn, ...]
    predecessor_turn_ids: tuple[str, ...]
    cutoff_turn_index: int
    transcript_hash: str
    receipts: tuple[SnapshotRetrievalReceipt, ...] = ()
    # Server-assigned query catalog.  Mappings keep this DTO independent from
    # the evidence persistence adapter while still exposing exact query IDs to
    # the provider-facing canonical payload.
    queries: tuple[Mapping[str, object], ...] = ()
    pending_question: PendingQuestion | None = None

    def __post_init__(self) -> None:
        if self.rule_set_id != "ordered_multi_expert_mutual_learning_v1":
            raise ValueError("mutual-learning prompts require their versioned RuleSet")
        if self.participant.snapshot_id == "":
            raise ValueError("participant snapshot is required")
        if self.predecessor_turn_ids != tuple(item.turn_id for item in self.predecessors):
            raise ValueError("predecessor_turn_ids must match visible prior rounds")
        if any(item.round_no >= self.turn_plan.round_no for item in self.predecessors):
            raise ValueError("same-round or future turn crossed the round barrier")


@dataclass(frozen=True, slots=True)
class FinalReadyTurn:
    """Validated immutable text/structure ready for the separate TTS stage."""

    turn_id: str
    participant_id: str
    snapshot_id: str
    round_no: int
    turn_index: int
    speech: str
    structured: StructuredTurnResult | MutualLearningTurnResultV1
    retrieval_status: RetrievalStatus
    grounding_mode: GroundingMode
    used_receipts: tuple[SnapshotRetrievalReceipt, ...]
    predecessor_turn_ids: tuple[str, ...]
    cutoff_turn_index: int
    transcript_hash: str
    attempt: Literal[1, 2]
    publication_status: Literal["final_ready", "public"] = "final_ready"
    evidence_trace: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.speech != self.structured.speech:
            raise ValueError("final-ready speech must match its structured result")
        if self.evidence_trace and isinstance(self.structured, MutualLearningTurnResultV1):
            # Import lazily: evidence_trace consumes these provider-neutral
            # types, while final-ready validation only needs it when an
            # optional trace has actually been attached.
            from .evidence_trace import public_evidence_trace, validate_exact_speech_span

            try:
                trace_rows = public_evidence_trace(self.evidence_trace)
            except ValueError as exc:
                raise ValueError("final-ready evidence trace is invalid") from exc
            key_ids = {claim.claim_id for claim in self.structured.key_claims}
            trace_ids = {row.claim_id for row in trace_rows}
            if any(row.turn_id != self.turn_id for row in trace_rows):
                raise ValueError("final-ready evidence trace crossed its turn")
            if not trace_ids.issubset(key_ids) or not key_ids.issubset(trace_ids):
                raise ValueError("final-ready evidence trace does not cover key claims")
            for row in trace_rows:
                try:
                    validate_exact_speech_span(self.speech, row.claim_text, row.speech_span)
                except ValueError as exc:
                    raise ValueError("final-ready evidence trace span is invalid") from exc
        structured_evidence_ids = (
            tuple(self.structured.used_evidence_id)
            if isinstance(self.structured, StructuredTurnResult)
            else self.structured.used_evidence_ids
        )
        if tuple(receipt.resolved_evidence_id() for receipt in self.used_receipts) != tuple(
            structured_evidence_ids
        ):
            raise ValueError("final-ready used receipts must match structured evidence IDs")
        if self.retrieval_status == "no_match" and self.grounding_mode != "general_reasoning":
            raise ValueError("no-match turns must use general_reasoning")
        if self.retrieval_status == "matched" and not self.used_receipts:
            raise ValueError("matched turns need used receipts")
        if self.grounding_mode == "mixed" and not self.used_receipts:
            raise ValueError("mixed turns need used receipts")
        if self.grounding_mode == "general_reasoning" and self.used_receipts:
            raise ValueError("general reasoning cannot carry source receipts")

    @property
    def question_id(self) -> str | None:
        question = self.structured.question
        return f"{self.turn_id}:question" if question.type != "none" else None

    @property
    def public_sources(self) -> tuple[PublicSource, ...]:
        return tuple(
            PublicSource(
                source_filename=receipt.source_filename,
                chunk_id=receipt.chunk_id,
                evidence_id=receipt.resolved_evidence_id(),
                rank=receipt.rank,
                score=receipt.score,
            )
            for receipt in self.used_receipts
        )


@dataclass(frozen=True, slots=True)
class ValidatedTurn:
    """Validator output with server-derived retrieval/grounding fields."""

    result: StructuredTurnResult | MutualLearningTurnResultV1
    retrieval_status: RetrievalStatus
    grounding_mode: GroundingMode
    used_receipts: tuple[SnapshotRetrievalReceipt, ...]
    public_sources: tuple[PublicSource, ...]
    word_count: int
    evidence_trace: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationContext:
    """All immutable state needed for one turn's RAG/LLM attempt."""

    debate_id: str
    topic: str
    turn: TurnPlan
    participant: ParticipantContext
    participants: tuple[ParticipantContext, ...]
    predecessors: tuple[FinalReadyTurn, ...] = ()
    pending_question: PendingQuestion | None = None

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.predecessors, key=lambda item: item.turn_index))
        if getattr(self.turn, "barrier", "prefix") == "round":
            # New mutual-learning plans may be built from a storage prefix
            # containing already-finalized same-round rows.  The prompt
            # adapter applies the actual barrier; future rows are never a
            # valid input even to that adapter.
            if any(item.round_no > self.turn.round_no for item in ordered):
                raise ValueError("future predecessor is not visible")
        elif tuple(item.turn_index for item in ordered) != tuple(range(self.turn.turn_index)):
            raise ValueError("invalid predecessor prefix")

    @property
    def effective_pending_question(self) -> PendingQuestion | None:
        """Use an explicit question or derive the latest assigned predecessor.

        Derivation keeps the setup/playback adapter small while preserving an
        exact question ID.  A caller-provided value remains authoritative and
        is validated against the current participant by :class:`TurnValidator`.
        """

        if self.pending_question is not None:
            return self.pending_question
        source_predecessors = self.predecessors
        if getattr(self.turn, "barrier", "prefix") == "round":
            from .mutual_learning_policy import pending_question_for_turn

            return pending_question_for_turn(
                self.predecessors,
                target_participant_id=self.participant.participant_id,
                current_round=self.turn.round_no,
            )
        for predecessor in reversed(source_predecessors):
            question = predecessor.structured.question
            if (
                question.type == "agent"
                and question.target_participant_id == self.participant.participant_id
                and question.text
            ):
                return PendingQuestion(
                    question_id=predecessor.question_id or f"{predecessor.turn_id}:question",
                    source_turn_id=predecessor.turn_id,
                    source_participant_id=predecessor.participant_id,
                    target_participant_id=self.participant.participant_id,
                    text=question.text,
                )
        return None


def mapping_to_dict(value: object) -> Mapping[str, object]:
    """Narrow helper for adapters that receive an untyped JSON object."""

    if not isinstance(value, Mapping):
        raise TurnValidationError("The provider response must be a JSON object.")
    return value


__all__ = [
    "FinalReadyTurn",
    "EngagementRelation",
    "ClaimType",
    "DisagreementCategory",
    "EvidenceTraceClaimType",
    "EvidenceTraceSupportMode",
    "EvidenceTraceClaimV1",
    "EngagementV1",
    "Engagement",
    "KeyClaim",
    "FinalDisagreementV1",
    "GenerationContext",
    "GenerationDiscarded",
    "GenerationFailed",
    "GroundingMode",
    "MutualLearningDisagreementV1",
    "MutualLearningEvidenceConflictV1",
    "MutualLearningPositionChangeV1",
    "MutualLearningSynthesisV1",
    "MutualLearningTurnResultV1",
    "MutualLearningTurnResult",
    "MutualLearningSynthesis",
    "MutualLearningPromptInput",
    "MutualPositionUpdate",
    "ParticipantContext",
    "PendingQuestion",
    "PublicSource",
    "RetrievalStatus",
    "SelectedEvidence",
    "SnapshotRetrievalReceipt",
    "Stance",
    "StanceMode",
    "StructuredTurnResult",
    "TurnPromptInput",
    "TurnQuestion",
    "TurnValidationError",
    "ValidatedTurn",
    "mapping_to_dict",
]
