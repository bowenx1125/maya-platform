"""Provider-neutral LLM port and deterministic Mock implementation.

Wave 2 intentionally does not ship a real text-model adapter.  The Mock
provider emits a stable structured object from the canonical prompt bytes and
offers explicit, test-only failure injection for the shared attempt-1/2
repair path.  The fixed Wave 4 adapter is re-exported at the end of this
module; its transport/output/privacy/accounting implementation lives in small
sibling modules so this historical Mock port remains stable.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Literal, Protocol, cast

from app.modules.agents.persona import PersonaProviderViewV1, PersonaSpecV1
from app.modules.agents.persona_mock import (
    bounded_teaching_dimensions_for_persona,
    teaching_dimensions_for_persona,
)
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.mutual_learning_prompts import (
    build_mutual_learning_prompt,
)
from app.modules.debates.generation.prompt_request import ProviderPromptV1
from app.modules.debates.generation.prompts import build_turn_prompt, prompt_hash
from app.modules.debates.generation.types import (
    EngagementV1,
    EvidenceTraceClaimV1,
    EvidenceTraceSupportMode,
    GenerationProviderError,
    KeyClaimV1,
    MutualLearningPromptInput,
    MutualLearningTurnResultV1,
    StructuredTurnResult,
    TurnPromptInput,
    TurnQuestion,
)

MutualClaimType = Literal["factual", "interpretation", "value_judgement", "proposal"]
_SPEECH_ALPHA_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")


def _complete_excerpt(value: str, *, max_words: int = 8) -> str:
    """Keep Mock evidence wording bounded without cutting a sentence in half."""

    normalized = " ".join(value.split()).strip()
    if not normalized:
        raise LLMStructuredOutputError("mock receipt text is empty")
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    for sentence in sentences:
        words = sentence.split()
        if words and len(words) <= max_words:
            return sentence.rstrip(".!?")
    words = normalized.split()
    # The explicit continuation clause makes the bounded excerpt a complete
    # statement rather than an arbitrary character/word fragment.  It is a
    # display projection only; the server still owns the full receipt text.
    # Two source words plus the four-word continuation clause stay within the
    # eight-word excerpt bound while making the truncation explicit and
    # sentence-complete inside the surrounding source statement.
    head = " ".join(words[: max_words - 6])
    return f"Excerpt begins {head}; receipt text continues elsewhere"


def _bounded_identity(value: str, *, max_words: int = 3) -> str:
    """Keep a display name readable without copying a long authored field."""

    normalized = " ".join(value.split()).strip()
    words = _SPEECH_ALPHA_WORD_RE.findall(normalized)
    if words and len(words) <= max_words and not re.search(r"\d", normalized):
        return normalized.rstrip(".!?")
    return "this expert"


def _bounded_question_excerpt(value: str, *, max_words: int = 8) -> str:
    """Project a pending question into a short, source-neutral phrase."""

    words = _SPEECH_ALPHA_WORD_RE.findall(" ".join(value.split()).strip())
    if not words:
        return "the assigned concern"
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[: max_words - 3]) + " and related concerns"


class LLMProviderError(GenerationProviderError):
    """A provider failure safe to pass through turn retry handling."""

    def __init__(
        self,
        message: str = "mock provider failure",
        *,
        acceptance_state: str = "unknown",
    ) -> None:
        super().__init__(message)
        self.acceptance_state = acceptance_state
        self.failure_kind = "transport_unknown"


class LLMStructuredOutputError(LLMProviderError):
    """A provider returned malformed JSON/shape instead of the closed DTO."""

    def __init__(self, message: str = "provider structured output invalid") -> None:
        super().__init__(message, acceptance_state="accepted")
        self.failure_kind = "structure_invalid"


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
        self, prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1
    ) -> StructuredTurnResult | MutualLearningTurnResultV1:
        """Generate one closed structured turn from a frozen prompt."""


@dataclass(frozen=True, slots=True)
class MockLLMCall:
    """Safe call trace for tests; no provider/model/key fields are included."""

    prompt_hash: str
    receipt_hash: str
    turn_id: str
    messages: tuple[tuple[str, str], ...] = ()


def _legacy_turn_prompt(
    prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1,
) -> TurnPromptInput:
    if not isinstance(prompt, TurnPromptInput):
        raise TypeError("the legacy Mock renderer requires a TurnPromptInput")
    return prompt


def _prompt_phase(
    prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1,
) -> str:
    if isinstance(prompt, ProviderPromptV1):
        return prompt.request.phase
    return prompt.turn_plan.phase


def _prompt_next_participant_id(
    prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1,
) -> str | None:
    if isinstance(prompt, ProviderPromptV1):
        return prompt.request.next_participant_id
    return prompt.turn_plan.next_participant_id


def _mutual_claims(
    speech: str,
    *,
    turn_id: str,
    source_sentence: str | None,
    used_evidence_ids: list[str],
    has_receipts: bool,
    core_claims: tuple[tuple[str, MutualClaimType], ...],
) -> tuple[list[KeyClaimV1], list[EvidenceTraceClaimV1]]:
    """Build Mock claims from exact spans already present in the speech.

    Provider claim IDs are placeholders only.  The server derives the final
    IDs after validating each exact speech span and receipt boundary.
    """

    candidates: list[tuple[str, MutualClaimType, list[str]]] = []
    if source_sentence is not None and used_evidence_ids:
        candidates.append((source_sentence, "interpretation", list(used_evidence_ids)))
    candidates.extend((text, claim_type, []) for text, claim_type in core_claims)
    if not candidates or any(text not in speech for text, _claim_type, _ids in candidates):
        raise LLMStructuredOutputError("mock could not construct exact mutual claim spans")
    claim_texts = [text for text, _claim_type, _ids in candidates]
    if len(claim_texts) != len(set(claim_texts)):
        raise LLMStructuredOutputError("mock produced duplicate mutual claim spans")
    claims = [
        KeyClaimV1(
            claim_id=f"{turn_id}:provider-claim-{index + 1}",
            claim_text=text,
            claim_type=claim_type,
            used_evidence_ids=evidence_ids,
        )
        for index, (text, claim_type, evidence_ids) in enumerate(candidates)
    ]
    default_mode = "general_reasoning" if has_receipts else "no_match"
    trace_claims = [
        EvidenceTraceClaimV1(
            claim_text=text,
            claim_type="background" if claim_type == "interpretation" else claim_type,
            used_evidence_ids=evidence_ids,
            support_mode=cast(EvidenceTraceSupportMode, "direct" if evidence_ids else default_mode),
        )
        for text, claim_type, evidence_ids in candidates
    ]
    return claims, trace_claims


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
        self, prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1
    ) -> StructuredTurnResult | MutualLearningTurnResultV1:
        self.calls += 1
        messages: tuple[tuple[str, str], ...] = ()
        if isinstance(prompt, ProviderPromptV1):
            request = prompt.request
            is_mutual = request.rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
            messages = tuple((message.role, message.content) for message in prompt.messages)
            rendered = "\x1e".join(content for _role, content in messages)
            receipt_hash = request.receipt_hash
            turn_id = request.turn_id
        else:
            is_mutual = prompt.rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
            rendered = (
                build_mutual_learning_prompt(prompt)  # type: ignore[arg-type]
                if is_mutual
                else build_turn_prompt(_legacy_turn_prompt(prompt))
            )
            receipt_hash = hashlib.sha256(
                "\x1f".join(receipt.resolved_evidence_id() for receipt in prompt.receipts).encode()
            ).hexdigest()
            turn_id = prompt.turn_plan.turn_id
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        self.call_log.append(
            MockLLMCall(
                prompt_hash=digest,
                receipt_hash=receipt_hash,
                turn_id=turn_id,
                messages=messages,
            )
        )
        failure = self._failures.popleft() if self._failures else None
        if failure in {"technical"}:
            raise LLMProviderError("mock technical provider failure", acceptance_state="not_sent")
        if failure in {"json", "shape"}:
            raise LLMStructuredOutputError("mock malformed structured output")
        if failure in {"word", "long"}:
            long_result: StructuredTurnResult | MutualLearningTurnResultV1 = (
                self._mutual_result(prompt)
                if is_mutual
                else self._valid_result(_legacy_turn_prompt(prompt))
            )
            return long_result.model_copy(update={"speech": " ".join(["word"] * 201) + "."})
        if failure == "short":
            short_result: StructuredTurnResult | MutualLearningTurnResultV1 = (
                self._mutual_result(prompt)
                if is_mutual
                else self._valid_result(_legacy_turn_prompt(prompt))
            )
            return short_result.model_copy(update={"speech": " ".join(["word"] * 79) + "."})
        if failure == "rule":
            if is_mutual:
                result = self._mutual_result(prompt)
                phase = _prompt_phase(prompt)
                next_participant_id = _prompt_next_participant_id(prompt)
                if phase == "opening":
                    return result.model_copy(
                        update={
                            "question": TurnQuestion(
                                type="agent",
                                target_participant_id=next_participant_id,
                                text="What do you think?",
                            )
                        }
                    )
                return result.model_copy(update={"engagements": []})
            legacy_prompt = _legacy_turn_prompt(prompt)
            legacy_result = self._valid_result(legacy_prompt)
            if legacy_prompt.turn_plan.round_no == 1:
                return legacy_result.model_copy(
                    update={
                        "question": TurnQuestion(
                            type="agent",
                            target_participant_id=legacy_prompt.turn_plan.next_participant_id,
                            text="What do you think?",
                        )
                    }
                )
            return legacy_result.model_copy(update={"rebuttal_target_turn_id": None})
        if failure == "matched_but_unused":
            if is_mutual:
                mutual_result = self._mutual_result(prompt)
                return mutual_result.model_copy(
                    update={
                        "used_evidence_id": [],
                        "key_claims": [
                            claim.model_copy(update={"used_evidence_ids": []})
                            for claim in mutual_result.key_claims
                        ],
                    }
                )
            legacy_result = self._valid_result(_legacy_turn_prompt(prompt))
            return legacy_result.model_copy(update={"used_evidence_id": []})
        if failure is not None:
            raise LLMProviderError("unknown mock failure injection")
        return (
            self._mutual_result(prompt)
            if is_mutual
            else self._valid_result(_legacy_turn_prompt(prompt))
        )

    def _mutual_result(
        self,
        prompt: TurnPromptInput | MutualLearningPromptInput | ProviderPromptV1,
    ) -> MutualLearningTurnResultV1:
        if isinstance(prompt, ProviderPromptV1):
            request = prompt.request
            compatibility = SimpleNamespace(
                participant=SimpleNamespace(
                    agent_name=request.persona_provider_view.identity.name,
                    participant_id=request.participant_id,
                    persona=request.persona_provider_view,
                ),
                phase=request.phase,
                receipts=tuple(
                    SimpleNamespace(
                        text=evidence.excerpt,
                        resolved_evidence_id=lambda evidence_id=evidence.evidence_id: evidence_id,
                    )
                    for evidence in request.evidence_catalog
                ),
                predecessors=tuple(
                    SimpleNamespace(
                        turn_id=predecessor.turn_id,
                        participant_id=predecessor.participant_id,
                        structured=SimpleNamespace(key_claims=predecessor.key_claims),
                    )
                    for predecessor in request.predecessors
                ),
                pending_question=(
                    SimpleNamespace(
                        question_id=request.pending_question.question_id,
                        text=request.pending_question.text,
                    )
                    if request.pending_question is not None
                    else None
                ),
                turn_plan=SimpleNamespace(
                    turn_id=request.turn_id,
                    next_participant_id=request.next_participant_id,
                ),
            )
            return self._valid_mutual_result(cast(MutualLearningPromptInput, compatibility))
        if isinstance(prompt, TurnPromptInput):
            raise TypeError("the mutual Mock renderer requires a mutual-learning prompt")
        return self._valid_mutual_result(prompt)

    def _valid_mutual_result(self, prompt: MutualLearningPromptInput) -> MutualLearningTurnResultV1:
        """Emit a deterministic valid object for every resolved phase."""

        receipt_ids = [receipt.resolved_evidence_id() for receipt in prompt.receipts]
        used = receipt_ids[:1]
        participant = prompt.participant
        persona = getattr(participant, "persona", None)
        dimensions = (
            teaching_dimensions_for_persona(persona)
            if isinstance(persona, (PersonaSpecV1, PersonaProviderViewV1))
            else None
        )
        speech_dimensions = (
            bounded_teaching_dimensions_for_persona(persona)
            if isinstance(persona, (PersonaSpecV1, PersonaProviderViewV1))
            else None
        )
        safe_name = _bounded_identity(participant.agent_name)
        teaching_line = (
            ""
            if speech_dimensions is None
            else (
                f"{speech_dimensions.tone_sentence} "
                f"{speech_dimensions.value_priority_sentence} "
                f"{speech_dimensions.argument_pattern_sentence} "
                f"{speech_dimensions.concession_style_sentence} "
                f"{speech_dimensions.debate_strategy_sentence} "
                f"{speech_dimensions.question_style_sentence} "
            )
        )
        phase = prompt.phase
        source_excerpt = ""
        if used:
            source_excerpt = _complete_excerpt(prompt.receipts[0].text)
            evidence_line = (
                f'The current snapshot passage says, "{source_excerpt}". '
                "I use it only as this participant's bounded evidence."
            )
        else:
            evidence_line = (
                "No relevant passage was retrieved, so this is honest general reasoning "
                "without a claimed source."
            )
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
            question_excerpt = _bounded_question_excerpt(prompt.pending_question.text)
            answer_text = (
                f'I answer the assigned question directly: "{question_excerpt}". '
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
                f"{teaching_line}"
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
            claims, trace_claims = _mutual_claims(
                speech,
                turn_id=prompt.turn_plan.turn_id,
                source_sentence=(
                    f'The current snapshot passage says, "{source_excerpt}".' if used else None
                ),
                used_evidence_ids=used,
                has_receipts=bool(prompt.receipts),
                core_claims=(
                    (
                        "My focus is to protect agency while taking public safety and community "
                        "effects seriously.",
                        "interpretation",
                    ),
                    (
                        "One key point is that a policy should be transparent enough to be "
                        "examined.",
                        "proposal",
                    ),
                    (
                        "A second key point is that safeguards should leave room for responsible "
                        "innovation.",
                        "proposal",
                    ),
                ),
            )
            return MutualLearningTurnResultV1(
                speech=speech,
                key_claims=claims,
                evidence_trace_claims=trace_claims,
                position_summary=(
                    "Balance agency, safety, innovation, and community effects through "
                    "accountable safeguards"
                    + (
                        f", prioritizing {dimensions.value_priority}."
                        if dimensions is not None
                        else "."
                    )
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
                f"{teaching_line}"
                f"{engagement_text}{answer_text}{evidence_line} "
                "I learned that accountability requires visible trade-offs and correction. "
                "My final position adds review, community voice, and evidence boundaries. "
                "The remaining uncertainty is whether implementation would distribute "
                "burdens fairly. "
                "My final recommendation is transparent safeguards with independent review "
                "and correction. "
                "Reasonable differences remain."
            )
            claims, trace_claims = _mutual_claims(
                speech,
                turn_id=prompt.turn_plan.turn_id,
                source_sentence=(
                    f'The current snapshot passage says, "{source_excerpt}".' if used else None
                ),
                used_evidence_ids=used,
                has_receipts=bool(prompt.receipts),
                core_claims=(
                    (
                        "I learned that accountability requires visible trade-offs and correction.",
                        "interpretation",
                    ),
                    (
                        "My final position adds review, community voice, and evidence boundaries.",
                        "interpretation",
                    ),
                    (
                        "My final recommendation is transparent safeguards with independent review "
                        "and correction.",
                        "proposal",
                    ),
                ),
            )
            return MutualLearningTurnResultV1(
                speech=speech,
                key_claims=claims,
                evidence_trace_claims=trace_claims,
                engagements=list(engagement),
                answered_question_ids=answered,
                learned_from_others=[
                    "The discussion made accountability and correction mechanisms more explicit."
                ],
                position_summary=(
                    "Recommend transparent safeguards, independent review, and an "
                    "affected-community correction path"
                    + (
                        f", prioritizing {dimensions.value_priority}."
                        if dimensions is not None
                        else "."
                    )
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
            f"As {safe_name}, I continue from the earlier round. {teaching_line}"
            f"{engagement_text}{answer_text}"
            f"{evidence_line} I keep the exchange civil and update my position toward "
            "transparent safeguards, "
            "independent review, and an opportunity for affected communities to be heard. "
            f"{question_text} I mark the remaining uncertainty as the fair distribution of burdens."
        )
        claims, trace_claims = _mutual_claims(
            speech,
            turn_id=prompt.turn_plan.turn_id,
            source_sentence=(
                f'The current snapshot passage says, "{source_excerpt}".' if used else None
            ),
            used_evidence_ids=used,
            has_receipts=bool(prompt.receipts),
            core_claims=(
                (
                    "I keep the exchange civil and update my position toward transparent "
                    "safeguards, independent review, and an opportunity for affected "
                    "communities to be heard.",
                    "interpretation",
                ),
                (
                    "I mark the remaining uncertainty as the fair distribution of burdens.",
                    "value_judgement",
                ),
            ),
        )
        return MutualLearningTurnResultV1(
            speech=speech,
            key_claims=claims,
            evidence_trace_claims=trace_claims,
            engagements=list(engagement),
            answered_question_ids=answered,
            position_summary=(
                "Refine the balance toward transparent safeguards, independent review, "
                "and community voice"
                + (
                    f", prioritizing {dimensions.value_priority}."
                    if dimensions is not None
                    else "."
                )
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

# Import after the Mock definitions so the historical provider port and its
# error classes remain available while the fixed Wave 4 implementation stays
# in small sibling modules.
from app.providers.llm_adapter import (  # noqa: E402
    DashScopeLLMAdapter,
    DashScopeLLMConfig,
    DashScopeLLMProvider,
    FixedDashScopeLLMAdapter,
    LLMAcceptedCandidateV1,
    LLMAdapter,
    LLMAdapterError,
    LLMRequest,
    LLMRequestV1,
    LLMResponseError,
    LLMUsage,
    LLMUsageV1,
    LLMValidatedResultV1,
    ValidatedLLMResult,
)
from app.providers.llm_output import (  # noqa: E402
    LLMOutputError,
    LLMOutputValidationError,
    MappedLLMTurnV1,
    RepairFeedbackV1,
    map_llm_output,
    map_provider_output,
)
from app.providers.llm_price_card import (  # noqa: E402
    LLMBudgetCapV1,
    LLMPriceCardError,
    LLMPriceCardV1,
    actual_cost,
    debate_budget_cap,
    reservation_cost,
)
from app.providers.llm_privacy import (  # noqa: E402
    LLMOutboundManifestV1,
    LLMOutboundPrivacyError,
    LLMOutboundScanResult,
    scan_llm_outbound_messages,
)
from app.providers.llm_tokenizer import (  # noqa: E402
    ConservativeLLMTokenizer,
    LLMTokenizerError,
    LLMTokenizerPort,
    PinnedLLMTokenizer,
)
from app.providers.llm_transport import (  # noqa: E402
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMHTTPRejected,
    LLMTransport,
    LLMTransportError,
    LLMTransportNotSent,
    LLMTransportResponse,
)

__all__ += [
    "ConservativeLLMTokenizer",
    "DashScopeLLMAdapter",
    "DashScopeLLMConfig",
    "DashScopeLLMProvider",
    "FixedDashScopeLLMAdapter",
    "HttpxLLMTransport",
    "LLMAcceptanceUnknown",
    "LLMAcceptedCandidateV1",
    "LLMHTTPRejected",
    "LLMAdapter",
    "LLMAdapterError",
    "LLMBudgetCapV1",
    "LLMOutboundManifestV1",
    "LLMOutboundPrivacyError",
    "LLMOutboundScanResult",
    "LLMOutputError",
    "LLMOutputValidationError",
    "LLMPriceCardError",
    "LLMPriceCardV1",
    "LLMRequest",
    "LLMRequestV1",
    "LLMResponseError",
    "LLMTokenizerError",
    "LLMTokenizerPort",
    "LLMTransport",
    "LLMTransportError",
    "LLMTransportNotSent",
    "LLMTransportResponse",
    "LLMUsage",
    "LLMUsageV1",
    "LLMValidatedResultV1",
    "MappedLLMTurnV1",
    "PinnedLLMTokenizer",
    "RepairFeedbackV1",
    "ValidatedLLMResult",
    "actual_cost",
    "debate_budget_cap",
    "map_llm_output",
    "map_provider_output",
    "reservation_cost",
    "scan_llm_outbound_messages",
]
