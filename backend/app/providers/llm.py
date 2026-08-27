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
from typing import Literal, Protocol

from app.modules.debates.generation.prompts import build_turn_prompt, prompt_hash
from app.modules.debates.generation.types import (
    GenerationProviderError,
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

    def generate_turn(self, prompt: TurnPromptInput) -> StructuredTurnResult:
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

    def generate_turn(self, prompt: TurnPromptInput) -> StructuredTurnResult:
        self.calls += 1
        rendered = build_turn_prompt(prompt)
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
            result = self._valid_result(prompt)
            return result.model_copy(update={"speech": " ".join(["word"] * 201) + "."})
        if failure == "short":
            result = self._valid_result(prompt)
            return result.model_copy(update={"speech": " ".join(["word"] * 79) + "."})
        if failure == "rule":
            result = self._valid_result(prompt)
            if prompt.turn_plan.round_no == 1:
                return result.model_copy(
                    update={
                        "question": TurnQuestion(
                            type="agent",
                            target_participant_id=prompt.turn_plan.next_participant_id,
                            text="What do you think?",
                        )
                    }
                )
            return result.model_copy(update={"rebuttal_target_turn_id": None})
        if failure == "matched_but_unused":
            result = self._valid_result(prompt)
            return result.model_copy(update={"used_evidence_id": []})
        if failure is not None:
            raise LLMProviderError("unknown mock failure injection")
        return self._valid_result(prompt)

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
