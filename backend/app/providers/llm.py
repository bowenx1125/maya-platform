"""Provider-neutral LLM port and deterministic Mock implementation.

Wave 2 intentionally does not ship a real text-model adapter.  The Mock
provider emits a stable structured object from the canonical prompt bytes and
offers explicit, test-only failure injection for the shared attempt-1/2
repair path.  A future reviewed adapter can implement the same protocol
without changing the generation service or public DTOs.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.mutual_learning_prompts import (
    build_mutual_learning_prompt,
)
from app.modules.debates.generation.prompts import build_turn_prompt, prompt_hash
from app.modules.debates.generation.types import (
    EngagementV1,
    GenerationProviderError,
    KeyClaimV1,
    MutualLearningPromptInput,
    MutualLearningTurnResultV1,
    StructuredTurnResult,
    TurnPromptInput,
    TurnQuestion,
)


class LLMProviderError(GenerationProviderError):
    """A provider failure safe to pass through turn retry handling."""


class LLMStructuredOutputError(LLMProviderError):
    """A provider returned malformed JSON/shape instead of the closed DTO."""


FailureKind = Literal[
    "technical",
    "json",
    "shape",
    "word",
    "short",
    "long",
    "rule",
    "matched_but_unused",
]


class LLMProvider(Protocol):
    """The only text generation operation owned by M11."""

    def generate_turn(
        self, prompt: TurnPromptInput | MutualLearningPromptInput
    ) -> StructuredTurnResult | MutualLearningTurnResultV1:
        """Generate one closed structured turn from a frozen prompt."""


@dataclass(frozen=True, slots=True)
class MockLLMCall:
    """Safe call trace for tests; no provider/model/key fields are included."""

    prompt_hash: str
    receipt_hash: str
    turn_id: str


@dataclass
class MockLLMProvider:
    """Byte-stable local model double with explicit adversarial injections."""

    failures: Iterable[str] = ()
    calls: int = field(default=0, init=False)
    call_log: list[MockLLMCall] = field(default_factory=list, init=False)
    _failures: deque[str] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        self._failures.extend(str(item) for item in self.failures)

    @property
    def call_count(self) -> int:
        return self.calls

    @property
    def prompts(self) -> tuple[MockLLMCall, ...]:
        return tuple(self.call_log)

    def fail_next(self, kind: str) -> None:
        """Queue a test-only failure without making production configuration."""

        self._failures.append(kind)

    def generate_turn(
        self, prompt: TurnPromptInput | MutualLearningPromptInput
    ) -> StructuredTurnResult | MutualLearningTurnResultV1:
        self.calls += 1
        is_mutual = getattr(prompt, "rule_set_id", None) == MUTUAL_LEARNING_RULE_SET_ID
        rendered = (
            build_mutual_learning_prompt(prompt)  # type: ignore[arg-type]
            if is_mutual
            else build_turn_prompt(cast(TurnPromptInput, prompt))
        )
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        receipt_hash = hashlib.sha256(
            "\x1f".join(receipt.resolved_evidence_id() for receipt in prompt.receipts).encode()
        ).hexdigest()
        self.call_log.append(
            MockLLMCall(
                prompt_hash=digest, receipt_hash=receipt_hash, turn_id=prompt.turn_plan.turn_id
            )
        )
        failure = self._failures.popleft() if self._failures else None
        if failure in {"technical"}:
            raise LLMProviderError("mock technical provider failure")
        if failure in {"json", "shape"}:
            raise LLMStructuredOutputError("mock malformed structured output")
        if failure in {"word", "long"}:
            long_result: StructuredTurnResult | MutualLearningTurnResultV1 = (
                self._valid_mutual_result(prompt)  # type: ignore[arg-type]
                if is_mutual
                else self._valid_result(prompt)  # type: ignore[arg-type]
            )
            return long_result.model_copy(update={"speech": " ".join(["word"] * 201) + "."})
        if failure == "short":
            short_result: StructuredTurnResult | MutualLearningTurnResultV1 = (
                self._valid_mutual_result(prompt)  # type: ignore[arg-type]
                if is_mutual
                else self._valid_result(prompt)  # type: ignore[arg-type]
            )
            return short_result.model_copy(update={"speech": " ".join(["word"] * 79) + "."})
        if failure == "rule":
            if is_mutual:
                result = self._valid_mutual_result(prompt)  # type: ignore[arg-type]
                if getattr(prompt.turn_plan, "phase", "") == "opening":
                    return result.model_copy(
                        update={
                            "question": TurnQuestion(
                                type="agent",
                                target_participant_id=prompt.turn_plan.next_participant_id,
                                text="What do you think?",
                            )
                        }
                    )
                return result.model_copy(update={"engagements": []})
            legacy_result = self._valid_result(cast(TurnPromptInput, prompt))
            if prompt.turn_plan.round_no == 1:
                return legacy_result.model_copy(
                    update={
                        "question": TurnQuestion(
                            type="agent",
                            target_participant_id=prompt.turn_plan.next_participant_id,
                            text="What do you think?",
                        )
                    }
                )
            return legacy_result.model_copy(update={"rebuttal_target_turn_id": None})
        if failure == "matched_but_unused":
            if is_mutual:
                mutual_result = self._valid_mutual_result(prompt)  # type: ignore[arg-type]
                return mutual_result.model_copy(
                    update={
                        "used_evidence_id": [],
                        "key_claims": [
                            claim.model_copy(update={"used_evidence_ids": []})
                            for claim in mutual_result.key_claims
                        ],
                    }
                )
            legacy_result = self._valid_result(cast(TurnPromptInput, prompt))
            return legacy_result.model_copy(update={"used_evidence_id": []})
        if failure is not None:
            raise LLMProviderError("unknown mock failure injection")
        return (
            self._valid_mutual_result(prompt)  # type: ignore[arg-type]
            if is_mutual
            else self._valid_result(prompt)  # type: ignore[arg-type]
        )

    def _valid_mutual_result(self, prompt: MutualLearningPromptInput) -> MutualLearningTurnResultV1:
        """Emit a deterministic valid object for every resolved phase."""

        receipt_ids = [receipt.resolved_evidence_id() for receipt in prompt.receipts]
        used = receipt_ids[:1]
        participant = prompt.participant
        safe_name = (
            participant.agent_name
            if not any(character.isdigit() for character in participant.agent_name)
            else "this expert"
        )
        phase = prompt.phase
        source_excerpt = ""
        if used:
            source_excerpt = " ".join(prompt.receipts[0].text.split())[:140]
            evidence_line = (
                f'The current snapshot passage says, "{source_excerpt}". '
                "I use it only as this participant's bounded evidence."
            )
        else:
            evidence_line = (
                "No relevant passage was retrieved, so this is honest general reasoning "
                "without a claimed source."
            )
        claim_evidence = used
        claims = [
            KeyClaimV1(
                claim_id=f"{prompt.turn_plan.turn_id}:claim-1",
                claim_text=(
                    "A responsible answer should balance agency, safety, and community effects."
                ),
                claim_type="interpretation",
                used_evidence_ids=claim_evidence,
            ),
            KeyClaimV1(
                claim_id=f"{prompt.turn_plan.turn_id}:claim-2",
                claim_text=(
                    "Transparent safeguards and review make a recommendation more accountable."
                ),
                claim_type="proposal",
                used_evidence_ids=[],
            ),
        ]
        predecessor = next(
            (
                item
                for item in prompt.predecessors
                if item.participant_id != participant.participant_id
            ),
            None,
        )
        engagement: tuple[EngagementV1, ...] = ()
        engagement_text = ""
        if predecessor is not None and phase != "opening":
            predecessor_claim = next(iter(getattr(predecessor.structured, "key_claims", ())), None)
            target_claim_id = getattr(predecessor_claim, "claim_id", None)
            engagement = (
                EngagementV1(
                    target_turn_id=predecessor.turn_id,
                    target_claim_id=target_claim_id,
                    relation="agree",
                    faithful_summary=(
                        "The earlier expert links the decision to accountable community effects."
                    ),
                    response_summary=(
                        "I agree that accountability should remain central while adding "
                        "a review path."
                    ),
                ),
            )
            engagement_text = (
                "I engage the earlier expert's claim faithfully and add a review path. "
            )
        answer_text = ""
        answered: list[str] = []
        if prompt.pending_question is not None and phase != "opening":
            answered = [prompt.pending_question.question_id]
            answer_text = (
                f"I answer the assigned question directly: {prompt.pending_question.text} "
                "A practical response should test the concern against the available evidence. "
            )
        question = TurnQuestion(type="none")
        question_text = ""
        if phase == "exchange":
            question_text = (
                "How would the next expert test this balance against their strongest concern?"
            )
            question = TurnQuestion(
                type="agent",
                target_participant_id=prompt.turn_plan.next_participant_id,
                text=question_text,
            )
        if phase == "opening":
            speech = (
                f"As {safe_name}, I understand the question from this expert's "
                "professional perspective. "
                "My focus is to protect agency while taking public safety and community "
                "effects seriously. "
                "One key point is that a policy should be transparent enough to be examined. "
                "A second key point is that safeguards should leave room for responsible "
                "innovation. "
                "A further key point is that affected communities need a meaningful way "
                "to report harm. "
                f"{evidence_line} I state this opening independently, acknowledge missing "
                "local context, "
                "and keep the position open to future learning."
            )
            return MutualLearningTurnResultV1(
                speech=speech,
                key_claims=claims,
                position_summary=(
                    "Balance agency, safety, innovation, and community effects through "
                    "accountable safeguards."
                ),
                position_update="unchanged",
                remaining_uncertainty=[
                    "Which local effects and affected voices are still missing?"
                ],
                missing_information=[
                    "Local impact details and affected-community testimony remain missing."
                ],
                used_evidence_id=used,
                question=question,
            )
        final = phase == "final_integration"
        if final:
            speech = (
                f"As {safe_name}, I return to my opening position and integrate what I learned. "
                f"{engagement_text}{answer_text}{evidence_line} "
                "I learned that an accountable answer must make its trade-offs visible "
                "and provide a route for correction. "
                "My final position is therefore more explicit about review, community "
                "voice, and evidence boundaries. "
                "The remaining uncertainty is whether implementation would distribute "
                "burdens fairly. "
                "My final recommendation is to adopt transparent safeguards with "
                "independent review and a correction path. "
                "I preserve reasonable differences about how much restriction is justified."
            )
            return MutualLearningTurnResultV1(
                speech=speech,
                key_claims=claims,
                engagements=list(engagement),
                answered_question_ids=answered,
                learned_from_others=[
                    "The discussion made accountability and correction mechanisms more explicit."
                ],
                position_summary=(
                    "Recommend transparent safeguards, independent review, and an "
                    "affected-community correction path."
                ),
                position_update="clarified",
                position_update_reason=(
                    "Earlier public claims clarified how review and correction should "
                    "accompany a safeguard."
                ),
                remaining_uncertainty=[
                    "Implementation may distribute burdens unevenly across communities."
                ],
                unresolved_issue=(
                    "The fair distribution of implementation burdens remains unresolved."
                ),
                used_evidence_id=used,
                change_from_opening=(
                    "The final position adds explicit independent review and a correction "
                    "path to the opening balance."
                ),
                final_consensus=[
                    "Accountable safeguards should be transparent and open to correction."
                ],
                final_recommendation=(
                    "Adopt transparent safeguards with independent review and a correction path."
                ),
                question=TurnQuestion(type="none"),
            )
        speech = (
            f"As {safe_name}, I continue from the earlier round. {engagement_text}{answer_text}"
            f"{evidence_line} I keep the exchange civil and update my position toward "
            "transparent safeguards, "
            "independent review, and an opportunity for affected communities to be heard. "
            f"{question_text} I mark the remaining uncertainty as the fair distribution of burdens."
        )
        return MutualLearningTurnResultV1(
            speech=speech,
            key_claims=claims,
            engagements=list(engagement),
            answered_question_ids=answered,
            position_summary=(
                "Refine the balance toward transparent safeguards, independent review, "
                "and community voice."
            ),
            position_update="clarified",
            position_update_reason=(
                "A prior public claim and the current snapshot evidence clarify the "
                "review requirement."
            ),
            remaining_uncertainty=["The fair distribution of policy burdens remains uncertain."],
            unresolved_issue="Implementation trade-offs need further discussion.",
            used_evidence_id=used,
            question=question,
        )

    def _valid_result(self, prompt: TurnPromptInput) -> StructuredTurnResult:
        # The hash influences deterministic phrase selection, but it is an
        # internal implementation detail and must never leak into classroom
        # speech or ordinary logs.
        style = "careful" if int(prompt_hash(prompt)[0], 16) % 2 == 0 else "practical"
        receipt_ids = [receipt.resolved_evidence_id() for receipt in prompt.receipts]
        used = receipt_ids[:1]
        participant = prompt.participant
        stance_text = prompt.assigned_stance or "an open, evolving perspective"
        if prompt.turn_plan.round_no == 1:
            evidence_excerpt = ""
            if used:
                source_text = prompt.receipts[0].text.strip()
                evidence_excerpt = " ".join(source_text.split())[:180]
            evidence_line = (
                "The assigned knowledge passage states, "
                f'"{evidence_excerpt}". I use that passage as a bounded reason, '
                "while keeping the source scope limited to this participant's snapshot."
                if used
                else (
                    "No relevant passage was retrieved, so I make a clearly general "
                    "argument without a citation."
                )
            )
            speech = (
                f"As {participant.agent_name}, I approach this question from {stance_text}. "
                "The first responsibility is to state a position that can be examined rather than "
                "treating disagreement as a personal conflict. My central claim is that decisions "
                "about recommendation systems should balance individual agency, public safety, "
                "innovation, and the practical effects on communities. "
                f"{evidence_line} "
                "That distinction matters because a rule can address a real harm while creating "
                "a different burden for creators, small businesses, or minority voices. "
                "I therefore "
                "support a transparent standard, measurable safeguards, and meaningful oversight, "
                "while recognizing that reasonable people may weigh those safeguards differently. "
                f"This {style} opening summary keeps "
                "the claim open to respectful challenge."
            )
            return StructuredTurnResult(
                speech=speech,
                rebuttal_summary="",
                new_argument_summary=(
                    "Recommendation decisions should balance agency, safety, innovation, "
                    "and community effects."
                ),
                turn_summary=(
                    "The opening position favors transparent, measurable safeguards and "
                    "accountable oversight."
                ),
                position_summary=(
                    "Balance user agency, public safety, innovation, and community effects "
                    "through accountable safeguards."
                ),
                position_update="unchanged",
                used_evidence_id=used,
                question=TurnQuestion(type="none"),
            )

        predecessor = next(
            (
                item
                for item in prompt.predecessors
                if item.participant_id != participant.participant_id
            ),
            None,
        )
        target_turn_id = predecessor.turn_id if predecessor is not None else None
        target_claim = (
            predecessor.structured.position_summary
            if predecessor is not None
            else "the earlier participant's specific claim"
        )
        pending = prompt.pending_question
        answer = (
            f"I answer the question '{pending.text}' directly: it deserves a concrete "
            "safeguard and evidence-based review. "
            if pending is not None
            else "I also address the concern left open by the earlier exchange. "
        )
        if prompt.turn_plan.is_final:
            question = (
                "What principle should our class carry forward when a policy protects people "
                "but may also limit choice?"
            )
            question_shape = TurnQuestion(type="audience_reflection", text=question)
        else:
            question = (
                "How would the next participant test this balance against their strongest "
                f"concern about {prompt.topic.strip()}?"
            )
            question_shape = TurnQuestion(
                type="agent",
                target_participant_id=prompt.turn_plan.next_participant_id,
                text=question,
            )
        evidence_excerpt = ""
        if used:
            source_text = prompt.receipts[0].text.strip()
            evidence_excerpt = " ".join(source_text.split())[:180]
        evidence_line = (
            f'A relevant assigned passage says, "{evidence_excerpt}". '
            "I use that concrete passage to qualify the claim, but it does not decide "
            "the value judgment for us. "
            if used
            else (
                "Because no relevant passage was found, I mark this as general reasoning "
                "and do not invent a source. "
            )
        )
        speech = (
            f"I appreciate the specificity of the earlier claim: {target_claim}. "
            f"{answer}My response is a refinement, not a dismissal. {evidence_line} "
            "A responsible policy should identify a concrete risk, explain who bears its cost, "
            "and include review points that can correct unintended effects. That approach leaves "
            "room to acknowledge useful innovation while refusing to treat popularity as proof of "
            "safety. I would revise my emphasis toward transparent safeguards, independent review, "
            "and a genuine path for affected communities to be heard. "
            f"{question} The discussion is stronger when each side answers the actual concern, "
            f"and this {style} position update follows the evidence and the discussion."
        )
        return StructuredTurnResult(
            speech=speech,
            answered_question_id=pending.question_id if pending is not None else None,
            rebuttal_target_turn_id=target_turn_id,
            rebuttal_summary=(
                "The earlier claim deserves a direct answer; safeguards should address harm "
                "without treating popularity as proof."
            ),
            new_argument_summary=(
                "Transparent safeguards, independent review, and a correction path balance "
                "policy benefits and costs."
            ),
            turn_summary=(
                "The response refines the position through a specific rebuttal, evidence "
                "boundary, and focused question."
            ),
            position_summary=(
                "Refine the balance toward transparent safeguards, independent review, "
                "and affected-community voice."
            ),
            position_update="refined",
            position_update_reason=(
                "The earlier claim and the current evidence boundary justify emphasizing "
                "review and correction mechanisms."
            ),
            used_evidence_id=used,
            question=question_shape,
        )


def validate_llm_provider_selector(selector: str) -> None:
    """Fail closed: Wave 2 has no unreviewed real LLM implementation."""

    if selector != "mock":
        raise RuntimeError("Wave 2 LLM provider must be mock until separately audited")


def llm_provider(settings: object | None = None, *, selector: str | None = None) -> LLMProvider:
    """Return the callable Mock selector; reject real/unknown providers."""

    chosen = selector
    if chosen is None:
        chosen = getattr(settings, "llm_provider", "mock") if settings is not None else "mock"
    validate_llm_provider_selector(str(chosen))
    return MockLLMProvider()


# Descriptive aliases make the fail-closed seam easy to discover in callers.
select_llm_provider = llm_provider
get_llm_provider = llm_provider


__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "LLMStructuredOutputError",
    "MockLLMCall",
    "MockLLMProvider",
    "get_llm_provider",
    "llm_provider",
    "select_llm_provider",
    "validate_llm_provider_selector",
]
