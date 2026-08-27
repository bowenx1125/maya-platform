"""Single-turn generation orchestration over the M11 pure contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from .fencing import GenerationFence, GenerationFenceError, TurnClaim
from .prompts import make_turn_prompt_input
from .retrieval import (
    RAGRetrievalError,
    SnapshotRetriever,
    TurnSubquery,
    build_turn_subqueries,
)
from .types import (
    FinalReadyTurn,
    GenerationContext,
    GenerationDiscarded,
    GenerationFailed,
    GenerationProviderError,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    StructuredTurnResult,
    TurnPromptInput,
    TurnValidationError,
    ValidatedTurn,
)
from .validator import TurnValidator, final_ready_turn


class Retriever(Protocol):
    def retrieve(
        self,
        snapshot_id: str,
        subqueries: Sequence[TurnSubquery | str],
    ) -> object:
        """Return an object with a ``receipts`` tuple."""


class TurnLLM(Protocol):
    def generate_turn(self, prompt: TurnPromptInput) -> StructuredTurnResult:
        """Generate a provider-neutral structured turn."""


@dataclass(frozen=True, slots=True)
class GenerationAttempt:
    """Safe per-attempt trace, useful for audit without provider metadata."""

    attempt: int
    retrieval_count: int = 0
    provider_called: bool = False
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Final-ready output and attempt trace; no TTS/public side effect."""

    final_ready: FinalReadyTurn
    attempts: tuple[GenerationAttempt, ...]


class TurnGenerationService:
    """Generate one turn with the shared attempt 1|2 repair budget.

    Semantic strict→relaxed retrieval is delegated to ``SnapshotRetriever``
    and does not consume this retry budget.  The service only returns a
    final-ready object; it never mutates participant position state, creates
    audio, emits public events, or invokes a future report/interaction stage.
    """

    def __init__(
        self,
        retriever: SnapshotRetriever | Retriever,
        llm: TurnLLM,
        *,
        validator: TurnValidator | None = None,
        fence: GenerationFence | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.validator = validator or TurnValidator()
        self.fence = fence

    def generate(
        self,
        context: GenerationContext,
        *,
        claim: TurnClaim | None = None,
    ) -> GenerationResult:
        attempts: list[GenerationAttempt] = []
        active_claim = claim
        for attempt in (1, 2):
            attempt_record = GenerationAttempt(attempt=attempt)
            try:
                subqueries = build_turn_subqueries(context)
                retrieval = self.retriever.retrieve(context.participant.snapshot_id, subqueries)
                receipts = self._receipts(retrieval)
                attempt_record = replace(attempt_record, retrieval_count=len(receipts))
                prompt = make_turn_prompt_input(context, receipts)
                if self.fence is not None:
                    active_claim = self._claim_for_attempt(
                        context,
                        attempt,
                        active_claim,
                        transcript_hash=prompt.transcript_hash,
                    )
                attempt_record = replace(attempt_record, provider_called=True)
                raw = self.llm.generate_turn(prompt)
                validated = self._validate_with_optional_trim(
                    raw,
                    attempt=attempt,
                    context=context,
                    receipts=receipts,
                )
                result = final_ready_turn(
                    validated,
                    turn_id=context.turn.turn_id,
                    participant_id=context.participant.participant_id,
                    snapshot_id=context.participant.snapshot_id,
                    round_no=context.turn.round_no,
                    turn_index=context.turn.turn_index,
                    predecessor_turn_ids=prompt.predecessor_turn_ids,
                    cutoff_turn_index=prompt.cutoff_turn_index,
                    transcript_hash=prompt.transcript_hash,
                    attempt=attempt,
                )
                if self.fence is not None:
                    if active_claim is None or not self.fence.complete(
                        active_claim,
                        stage="generation",
                        attempt=attempt,
                        predecessor_turn_ids=prompt.predecessor_turn_ids,
                        transcript_hash=prompt.transcript_hash,
                    ):
                        raise GenerationDiscarded(
                            "The turn generation result arrived after its fence changed."
                        )
                attempts.append(attempt_record)
                return GenerationResult(result, tuple(attempts))
            except GenerationDiscarded:
                raise
            except (
                RAGRetrievalError,
                GenerationProviderError,
                TurnValidationError,
                ValueError,
            ) as exc:
                attempts.append(
                    replace(
                        attempt_record,
                        failure_code=getattr(exc, "code", "turn_generation_failed"),
                    )
                )
                if self.fence is not None and active_claim is not None:
                    self.fence.release(active_claim)
                    active_claim = None
                if attempt == 2:
                    raise GenerationFailed(
                        "Turn generation failed after the shared two-attempt repair budget.",
                        attempt=attempt,
                    ) from exc
        # The loop always returns or raises; keep type checkers honest.
        raise GenerationFailed("Turn generation did not produce a result.")

    def _claim_for_attempt(
        self,
        context: GenerationContext,
        attempt: int,
        existing: TurnClaim | None,
        *,
        transcript_hash: str,
    ) -> TurnClaim:
        if existing is not None:
            # A claim from attempt one may only be reused for the same attempt;
            # failed attempt one is released before a fresh attempt-two CAS.
            if existing.attempt == attempt and existing.state == "running":
                if existing.transcript_hash != transcript_hash:
                    raise GenerationDiscarded("The predecessor transcript hash changed.")
                return existing
            self.fence.release(existing)  # type: ignore[union-attr]
        if self.fence is None:  # pragma: no cover - guarded by caller
            raise GenerationFenceError("generation fence is not configured")
        claimed = self.fence.claim_turn(
            context.debate_id,
            turn_id=context.turn.turn_id,
            turn_index=context.turn.turn_index,
            stage="generation",
            attempt=attempt,
            predecessor_turn_ids=tuple(item.turn_id for item in context.predecessors),
            # The prompt hash is computed after retrieval; the fence still
            # checks the exact predecessor IDs and the service binds the hash
            # before the provider is called.
            transcript_hash=transcript_hash,
        )
        if claimed is None:
            raise GenerationDiscarded("The turn is outside the current preparation window.")
        return claimed

    @staticmethod
    def _receipts(value: object) -> tuple[SnapshotRetrievalReceipt, ...]:
        receipts = getattr(value, "receipts", None)
        if not isinstance(receipts, tuple):
            try:
                receipts = tuple(receipts)  # type: ignore[arg-type]
            except TypeError as exc:
                raise RAGRetrievalError("The retriever returned no typed receipts.") from exc
        if not all(isinstance(item, SnapshotRetrievalReceipt) for item in receipts):
            raise RAGRetrievalError("The retriever returned an untyped receipt.", technical=False)
        return cast(tuple[SnapshotRetrievalReceipt, ...], receipts)

    def _validate_with_optional_trim(
        self,
        raw: object,
        *,
        attempt: int,
        context: GenerationContext,
        receipts: Sequence[SnapshotRetrievalReceipt],
    ) -> ValidatedTurn:
        try:
            return self.validator.validate(
                raw,  # type: ignore[arg-type]
                plan=context.turn,
                participant=context.participant,
                receipts=receipts,
                predecessors=context.predecessors,
                pending_question=context.effective_pending_question,
            )
        except TurnValidationError:
            if attempt != 2:
                raise
            # Long output may be shortened only on complete sentences; every
            # structural/rule/evidence check is rerun by this method.
            from .types import StructuredTurnResult

            parsed = StructuredTurnResult.from_provider(raw)  # type: ignore[arg-type]
            return self.validator.validate_after_sentence_trim(
                parsed,
                plan=context.turn,
                participant=context.participant,
                receipts=receipts,
                predecessors=context.predecessors,
                pending_question=context.effective_pending_question,
            )


@dataclass(slots=True)
class PositionHistoryRecord:
    participant_id: str
    turn_id: str
    before_summary: str
    after_summary: str
    update_type: str
    reason: str | None


@dataclass(slots=True)
class PositionLedger:
    """Public position state that changes only at explicit publication."""

    summaries: dict[str, str] = field(default_factory=dict)
    stances: dict[str, str | None] = field(default_factory=dict)
    history: list[PositionHistoryRecord] = field(default_factory=list)

    @classmethod
    def from_participants(cls, participants: Sequence[ParticipantContext]) -> PositionLedger:
        return cls(
            summaries={
                item.participant_id: item.effective_position_summary for item in participants
            },
            stances={
                item.participant_id: item.current_stance or item.initial_stance
                for item in participants
            },
        )

    def publish(
        self, turn: FinalReadyTurn, participant: ParticipantContext
    ) -> PositionHistoryRecord:
        """Apply a final-ready update only when caller has made it public."""

        if turn.publication_status != "public":
            raise GenerationDiscarded(
                "An unpublished final-ready turn cannot update public stance."
            )
        if turn.participant_id != participant.participant_id:
            raise GenerationDiscarded("Position publication participant does not match the turn.")
        before = self.summaries.get(participant.participant_id, "")
        after = turn.structured.position_summary
        if participant.stance_mode == "open" and turn.structured.new_stance is not None:
            raise TurnValidationError("An open participant cannot publish an enum stance.")
        if turn.structured.new_stance is not None:
            self.stances[participant.participant_id] = turn.structured.new_stance
        self.summaries[participant.participant_id] = after
        record = PositionHistoryRecord(
            participant_id=participant.participant_id,
            turn_id=turn.turn_id,
            before_summary=before,
            after_summary=after,
            update_type=turn.structured.position_update,
            reason=turn.structured.position_update_reason,
        )
        self.history.append(record)
        return record


def mark_public(turn: FinalReadyTurn) -> FinalReadyTurn:
    """Create the public view after playback/start acknowledgement."""

    if turn.publication_status == "public":
        return turn
    return replace(turn, publication_status="public")


__all__ = [
    "GenerationAttempt",
    "GenerationResult",
    "PositionHistoryRecord",
    "PositionLedger",
    "TurnGenerationService",
    "TurnLLM",
    "mark_public",
]
