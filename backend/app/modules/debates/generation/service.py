"""Single-turn generation orchestration over the M11 pure contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID

from .fencing import GenerationFence, GenerationFenceError, TurnClaim
from .mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from .mutual_learning_prompts import make_mutual_learning_prompt_input
from .mutual_learning_validator import MutualLearningValidator
from .policy import RULE_SET_ID, SUPPORTED_RULE_SET_IDS
from .prompt_attempt import (
    PromptAcceptanceState,
    PromptAttemptPolicy,
    PromptFailureKind,
)
from .prompt_budget import ConservativeUtf8TokenCounter, PromptBudgetError
from .prompt_request import (
    PromptRequestError,
    ProviderPromptV1,
    build_provider_prompt_from_mutual_input,
)
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
    MutualLearningPromptInput,
    MutualLearningTurnResultV1,
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
    def generate_turn(
        self, prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1
    ) -> StructuredTurnResult | MutualLearningTurnResultV1:
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
        rule_set_id: str = RULE_SET_ID,
        mock_retrieval_policy_id: str | None = None,
    ) -> None:
        if rule_set_id not in SUPPORTED_RULE_SET_IDS:
            raise ValueError("unsupported Debate rule set")
        if mock_retrieval_policy_id not in {None, MOCK_LEXICAL_ANCHOR_POLICY_ID}:
            raise ValueError("unsupported Mock retrieval policy")
        self.retriever = retriever
        self.llm = llm
        self.validator = validator or (
            MutualLearningValidator()
            if rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
            else TurnValidator()
        )
        self.fence = fence
        self.rule_set_id = rule_set_id
        self.mock_retrieval_policy_id = mock_retrieval_policy_id

    def generate(
        self,
        context: GenerationContext,
        *,
        claim: TurnClaim | None = None,
    ) -> GenerationResult:
        if self.rule_set_id == MUTUAL_LEARNING_RULE_SET_ID:
            if context.participant.persona is not None:
                return self._generate_mutual_learning_strict(context, claim=claim)
            return self._generate_mutual_learning(context, claim=claim)
        attempts: list[GenerationAttempt] = []
        active_claim = claim
        for attempt in (1, 2):
            attempt_record = GenerationAttempt(attempt=attempt)
            try:
                subqueries = build_turn_subqueries(context)
                if self.mock_retrieval_policy_id is None:
                    retrieval = self.retriever.retrieve(context.participant.snapshot_id, subqueries)
                elif isinstance(self.retriever, SnapshotRetriever):
                    retrieval = self.retriever.retrieve(
                        context.participant.snapshot_id,
                        subqueries,
                        policy_id=self.mock_retrieval_policy_id,
                        topic_anchor=context.topic,
                    )
                else:
                    raise RAGRetrievalError(
                        "The Mock lexical policy requires the snapshot retriever.",
                        technical=False,
                    )
                receipts = self._receipts(retrieval)
                attempt_record = replace(attempt_record, retrieval_count=len(receipts))
                prompt = make_turn_prompt_input(context, receipts, rule_set_id=self.rule_set_id)
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

    def _generate_mutual_learning_strict(
        self,
        context: GenerationContext,
        *,
        claim: TurnClaim | None,
    ) -> GenerationResult:
        """Use PromptRequestV1 when a confirmed structured Persona is present.

        Retrieval and the public predecessor fence are built once.  A second
        provider call can only reuse those exact values: validation repair adds
        pointer-only feedback and a proven pre-acceptance transport failure
        resends the same frozen request.  Legacy test contexts without a
        structured Persona continue through the historical RuleSet adapter.
        """

        attempts: list[GenerationAttempt] = []
        active_claim = claim
        first_attempt = GenerationAttempt(attempt=1)
        try:
            subqueries = build_turn_subqueries(context)
            if self.mock_retrieval_policy_id is None:
                retrieval = self.retriever.retrieve(context.participant.snapshot_id, subqueries)
            elif isinstance(self.retriever, SnapshotRetriever):
                retrieval = self.retriever.retrieve(
                    context.participant.snapshot_id,
                    subqueries,
                    policy_id=self.mock_retrieval_policy_id,
                    topic_anchor=context.topic,
                )
            else:
                raise RAGRetrievalError(
                    "The Mock lexical policy requires the snapshot retriever.",
                    technical=False,
                )
            receipts = self._receipts(retrieval)
            first_attempt = replace(first_attempt, retrieval_count=len(receipts))
            mutual_input = make_mutual_learning_prompt_input(context, receipts)
            provider_prompt = build_provider_prompt_from_mutual_input(
                mutual_input,
                persona=context.participant.persona,  # type: ignore[arg-type]
                persona_spec_hash_value=context.participant.persona_spec_hash,
            )
            if self.fence is not None:
                active_claim = self._claim_for_attempt(
                    context,
                    1,
                    active_claim,
                    transcript_hash=mutual_input.transcript_hash,
                    predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                )
        except (RAGRetrievalError, PromptBudgetError, PromptRequestError, ValueError) as exc:
            attempts.append(
                replace(first_attempt, failure_code=getattr(exc, "code", "turn_generation_failed"))
            )
            if self.fence is not None and active_claim is not None:
                self.fence.release(active_claim)
            raise GenerationFailed(
                "Turn generation failed before the provider request.", attempt=1
            ) from exc

        for attempt in (1, 2):
            attempt_record = first_attempt if attempt == 1 else GenerationAttempt(
                attempt=attempt,
                retrieval_count=len(receipts),
            )
            try:
                attempt_record = replace(attempt_record, provider_called=True)
                raw = self.llm.generate_turn(provider_prompt)
                validated = self._validate_mutual_strict(
                    raw,
                    context=context,
                    receipts=receipts,
                    predecessors=mutual_input.predecessors,
                )
                result = final_ready_turn(
                    validated,
                    turn_id=context.turn.turn_id,
                    participant_id=context.participant.participant_id,
                    snapshot_id=context.participant.snapshot_id,
                    round_no=context.turn.round_no,
                    turn_index=context.turn.turn_index,
                    predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                    cutoff_turn_index=mutual_input.cutoff_turn_index,
                    transcript_hash=mutual_input.transcript_hash,
                    attempt=attempt,
                )
                if self.fence is not None:
                    if active_claim is None or not self.fence.complete(
                        active_claim,
                        stage="generation",
                        attempt=attempt,
                        predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                        transcript_hash=mutual_input.transcript_hash,
                    ):
                        raise GenerationDiscarded(
                            "The turn generation result arrived after its fence changed."
                        )
                attempts.append(attempt_record)
                return GenerationResult(result, tuple(attempts))
            except GenerationDiscarded:
                raise
            except TurnValidationError as exc:
                attempts.append(
                    replace(
                        attempt_record,
                        failure_code=getattr(exc, "code", "turn_generation_failed"),
                    )
                )
                if attempt == 2:
                    if self.fence is not None and active_claim is not None:
                        self.fence.release(active_claim)
                        active_claim = None
                    raise GenerationFailed(
                        "Turn generation failed after the frozen structure-repair attempt.",
                        attempt=attempt,
                    ) from exc
                try:
                    # ``repair_feedback`` is the only permitted difference;
                    # the helper never receives a retriever and reuses the
                    # exact receipts/transcript/persona/rule values.
                    from .prompt_attempt import repair_prompt_request

                    repaired_request = repair_prompt_request(
                        provider_prompt.request,
                        safe_error_code=getattr(exc, "code", "output_schema_invalid"),
                        json_pointers=("/",),
                    )
                    provider_prompt = self._provider_prompt_with_request(
                        provider_prompt,
                        repaired_request,
                    )
                    if self.fence is not None:
                        active_claim = self._claim_for_attempt(
                            context,
                            2,
                            active_claim,
                            transcript_hash=mutual_input.transcript_hash,
                            predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                        )
                except (PromptRequestError, PromptBudgetError, ValueError) as repair_exc:
                    if self.fence is not None and active_claim is not None:
                        self.fence.release(active_claim)
                    raise GenerationFailed(
                        "Turn generation structure repair could not be prepared.", attempt=2
                    ) from repair_exc
            except (
                GenerationProviderError,
                PromptBudgetError,
                PromptRequestError,
                ValueError,
            ) as exc:
                attempts.append(
                    replace(
                        attempt_record,
                        failure_code=getattr(exc, "code", "turn_generation_failed"),
                    )
                )
                if (
                    getattr(exc, "failure_kind", None) == "structure_invalid"
                    and getattr(exc, "acceptance_state", None)
                    == PromptAcceptanceState.ACCEPTED
                ):
                    if attempt == 2:
                        if self.fence is not None and active_claim is not None:
                            self.fence.release(active_claim)
                            active_claim = None
                        raise GenerationFailed(
                            "Turn generation failed after the frozen structure-repair attempt.",
                            attempt=attempt,
                        ) from exc
                    try:
                        from .prompt_attempt import repair_prompt_request

                        repaired_request = repair_prompt_request(
                            provider_prompt.request,
                            safe_error_code="output_schema_invalid",
                            json_pointers=("/",),
                        )
                        provider_prompt = self._provider_prompt_with_request(
                            provider_prompt,
                            repaired_request,
                        )
                        if self.fence is not None:
                            active_claim = self._claim_for_attempt(
                                context,
                                2,
                                active_claim,
                                transcript_hash=mutual_input.transcript_hash,
                                predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                            )
                        continue
                    except (PromptRequestError, PromptBudgetError, ValueError) as repair_exc:
                        if self.fence is not None and active_claim is not None:
                            self.fence.release(active_claim)
                        raise GenerationFailed(
                            "Turn generation structure repair could not be prepared.", attempt=2
                        ) from repair_exc
                if self.fence is not None and active_claim is not None:
                    self.fence.release(active_claim)
                    active_claim = None
                acceptance = getattr(exc, "acceptance_state", PromptAcceptanceState.UNKNOWN)
                failure = (
                    PromptFailureKind.TRANSPORT_NOT_SENT
                    if acceptance == PromptAcceptanceState.NOT_SENT
                    else PromptFailureKind.TRANSPORT_UNKNOWN
                )
                decision = PromptAttemptPolicy().decide(
                    attempt_no=attempt,
                    failure=failure,
                    acceptance=acceptance,
                )
                if not decision.retry:
                    raise GenerationFailed(
                        "Turn generation failed without a safe retry.", attempt=attempt
                    ) from exc
                # A proven not-sent retry uses the same provider prompt and
                # frozen retrieval set.  Re-claim the unchanged fence.
                if self.fence is not None:
                    active_claim = self._claim_for_attempt(
                        context,
                        2,
                        active_claim,
                        transcript_hash=mutual_input.transcript_hash,
                        predecessor_turn_ids=mutual_input.predecessor_turn_ids,
                    )
                continue
        raise GenerationFailed("Turn generation did not produce a result.", attempt=2)

    def _validate_mutual_strict(
        self,
        raw: object,
        *,
        context: GenerationContext,
        receipts: Sequence[SnapshotRetrievalReceipt],
        predecessors: Sequence[FinalReadyTurn],
    ) -> ValidatedTurn:
        validator = self.validator
        if not isinstance(validator, MutualLearningValidator):
            raise TurnValidationError("The mutual-learning validator is not configured.")
        return validator.validate(
            raw,  # type: ignore[arg-type]
            plan=context.turn,
            participant=context.participant,
            participants=context.participants,
            receipts=receipts,
            predecessors=predecessors,
            pending_question=context.effective_pending_question,
        )

    @staticmethod
    def _provider_prompt_with_request(
        previous: ProviderPromptV1,
        request: object,
    ) -> ProviderPromptV1:
        from .prompt_budget import preflight_prompt_budget
        from .prompt_request import PromptMessageV1, PromptRequestV1

        if not isinstance(request, PromptRequestV1):
            raise PromptRequestError("the repaired prompt request is invalid")
        user = request.canonical_json()
        system = previous.system_message
        budget = preflight_prompt_budget(
            (system.content, user),
            request_bytes=len(user.encode("utf-8")),
            requested_output_tokens=previous.budget.requested_output_tokens,
            # The pure ProviderPrompt value intentionally does not retain a
            # callable tokenizer.  Strict service calls currently use the
            # conservative fallback; a custom adapter must rebuild through
            # ``build_provider_prompt`` with its same pinned port.
            token_counter=ConservativeUtf8TokenCounter(),
        )
        return ProviderPromptV1(
            request=request,
            messages=(system, PromptMessageV1(role="user", content=user)),
            budget=budget,
            request_hash=request.request_hash,
            system_rules_hash=previous.system_rules_hash,
        )

    def _generate_mutual_learning(
        self,
        context: GenerationContext,
        *,
        claim: TurnClaim | None,
    ) -> GenerationResult:
        """Run the same bounded retry seam with a round-barrier prompt."""

        attempts: list[GenerationAttempt] = []
        active_claim = claim
        for attempt in (1, 2):
            attempt_record = GenerationAttempt(attempt=attempt)
            try:
                subqueries = build_turn_subqueries(context)
                if self.mock_retrieval_policy_id is None:
                    retrieval = self.retriever.retrieve(context.participant.snapshot_id, subqueries)
                elif isinstance(self.retriever, SnapshotRetriever):
                    retrieval = self.retriever.retrieve(
                        context.participant.snapshot_id,
                        subqueries,
                        policy_id=self.mock_retrieval_policy_id,
                        topic_anchor=context.topic,
                    )
                else:
                    raise RAGRetrievalError(
                        "The Mock lexical policy requires the snapshot retriever.",
                        technical=False,
                    )
                receipts = self._receipts(retrieval)
                attempt_record = replace(attempt_record, retrieval_count=len(receipts))
                prompt = make_mutual_learning_prompt_input(context, receipts)
                if self.fence is not None:
                    active_claim = self._claim_for_attempt(
                        context,
                        attempt,
                        active_claim,
                        transcript_hash=prompt.transcript_hash,
                        predecessor_turn_ids=prompt.predecessor_turn_ids,
                    )
                attempt_record = replace(attempt_record, provider_called=True)
                raw = self.llm.generate_turn(prompt)
                validated = self._validate_mutual_with_optional_trim(
                    raw,
                    attempt=attempt,
                    context=context,
                    receipts=receipts,
                    predecessors=prompt.predecessors,
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
        raise GenerationFailed("Turn generation did not produce a result.")

    def _claim_for_attempt(
        self,
        context: GenerationContext,
        attempt: int,
        existing: TurnClaim | None,
        *,
        transcript_hash: str,
        predecessor_turn_ids: Sequence[str] | None = None,
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
            predecessor_turn_ids=tuple(
                predecessor_turn_ids
                if predecessor_turn_ids is not None
                else (item.turn_id for item in context.predecessors)
            ),
            # The prompt hash is computed after retrieval; the fence still
            # checks the exact predecessor IDs and the service binds the hash
            # before the provider is called.
            transcript_hash=transcript_hash,
        )
        if claimed is None:
            raise GenerationDiscarded("The turn is outside the current preparation window.")
        return claimed

    def _validate_mutual_with_optional_trim(
        self,
        raw: object,
        *,
        attempt: int,
        context: GenerationContext,
        receipts: Sequence[SnapshotRetrievalReceipt],
        predecessors: Sequence[FinalReadyTurn],
    ) -> ValidatedTurn:
        validator = self.validator
        if not isinstance(validator, MutualLearningValidator):
            raise TurnValidationError("The mutual-learning validator is not configured.")
        try:
            return validator.validate(
                raw,  # type: ignore[arg-type]
                plan=context.turn,
                participant=context.participant,
                participants=context.participants,
                receipts=receipts,
                predecessors=predecessors,
                pending_question=context.effective_pending_question,
            )
        except TurnValidationError:
            if attempt != 2:
                raise
            parsed = MutualLearningTurnResultV1.from_provider(raw)  # type: ignore[arg-type]
            return validator.validate_after_sentence_trim(
                parsed,
                plan=context.turn,
                participant=context.participant,
                participants=context.participants,
                receipts=receipts,
                predecessors=predecessors,
                pending_question=context.effective_pending_question,
            )

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
        validator = self.validator
        if not isinstance(validator, TurnValidator):
            raise TurnValidationError("The legacy validator is not configured.")
        try:
            return validator.validate(
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
            return validator.validate_after_sentence_trim(
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
        new_stance = getattr(turn.structured, "new_stance", None)
        if participant.stance_mode == "open" and new_stance is not None:
            raise TurnValidationError("An open participant cannot publish an enum stance.")
        if new_stance is not None:
            self.stances[participant.participant_id] = new_stance
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
