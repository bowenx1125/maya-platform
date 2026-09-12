"""Provider-neutral LLM port and deterministic Mock implementation.

The Mock emits a stable structured object from canonical prompt bytes and
offers explicit, test-only failure injection. The reviewed real adapter is
re-exported below; transport, output and accounting live in sibling modules.
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
    english_safe_dimension_value,
    teaching_dimensions_for_persona,
)
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.mutual_learning_prompts import (
    build_mutual_learning_prompt,
)
from app.modules.debates.generation.prompt_request import ProviderPromptV1
from app.modules.debates.generation.segments import (
    SegmentInputSnapshot,
    SegmentTurnResult,
    build_segment_system_prompt,
    validate_segment_output,
)
from app.modules.debates.generation.types import (
    EngagementV1,
    EvidenceTraceClaimV1,
    EvidenceTraceSupportMode,
    GenerationProviderError,
    KeyClaimV1,
    MutualLearningPromptInput,
    MutualLearningTurnResultV1,
    StructuredTurnResult,
    TurnQuestion,
)

MutualClaimType = Literal["factual", "interpretation", "value_judgement", "proposal"]
_SPEECH_ALPHA_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
_MOCK_MATCHING_PASSAGE_CLAIM = "A matching passage was retrieved from the current snapshot."


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


def _safe_receipt_claim(value: str) -> str:
    """Keep non-English receipt text in the inspector, never in speech.

    Receipt text remains untouched in the typed receipt and its server-owned
    lineage.  The Mock's authoritative English speech uses one truthful claim
    for any non-ASCII script instead of quoting or attempting translation.
    """

    normalized = " ".join(value.split()).strip()
    if any(ord(character) > 127 for character in normalized):
        return _MOCK_MATCHING_PASSAGE_CLAIM
    return f'The current snapshot passage says, "{_complete_excerpt(normalized)}".'


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
        self,
        prompt: MutualLearningPromptInput | ProviderPromptV1 | SegmentInputSnapshot,
    ) -> StructuredTurnResult | MutualLearningTurnResultV1 | SegmentTurnResult:
        """Generate one closed structured turn from a frozen prompt."""

    def generate_segments(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        repair_feedback: dict[str, object] | None = None,
    ) -> dict[str, object] | SegmentTurnResult:
        """Generate the explicit paragraph protocol from a frozen snapshot."""


@dataclass(frozen=True, slots=True)
class MockLLMCall:
    """Safe call trace for tests; no provider/model/key fields are included."""

    prompt_hash: str
    receipt_hash: str
    turn_id: str
    messages: tuple[tuple[str, str], ...] = ()


def _prompt_phase(
    prompt: MutualLearningPromptInput | ProviderPromptV1,
) -> str:
    if isinstance(prompt, ProviderPromptV1):
        return prompt.request.phase
    return prompt.turn_plan.phase


def _prompt_next_participant_id(
    prompt: MutualLearningPromptInput | ProviderPromptV1,
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
        self,
        prompt: MutualLearningPromptInput | ProviderPromptV1 | SegmentInputSnapshot,
    ) -> StructuredTurnResult | MutualLearningTurnResultV1 | SegmentTurnResult:
        if isinstance(prompt, SegmentInputSnapshot):
            return validate_segment_output(self.generate_segments(prompt), prompt)
        self.calls += 1
        messages: tuple[tuple[str, str], ...] = ()
        if isinstance(prompt, ProviderPromptV1):
            request = prompt.request
            rule_set_id = request.rule_set_id
            messages = tuple((message.role, message.content) for message in prompt.messages)
            rendered = "\x1e".join(content for _role, content in messages)
            receipt_hash = request.receipt_hash
            turn_id = request.turn_id
        else:
            rule_set_id = prompt.rule_set_id
            rendered = build_mutual_learning_prompt(prompt)
            receipt_hash = hashlib.sha256(
                "\x1f".join(receipt.resolved_evidence_id() for receipt in prompt.receipts).encode()
            ).hexdigest()
            turn_id = prompt.turn_plan.turn_id
        if rule_set_id != MUTUAL_LEARNING_RULE_SET_ID:
            raise LLMProviderError("the Mock provider supports only the mutual-learning rule set")
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
            return self._mutual_result(prompt).model_copy(
                update={"speech": " ".join(["word"] * 201) + "."}
            )
        if failure == "short":
            return self._mutual_result(prompt).model_copy(
                update={"speech": " ".join(["word"] * 79) + "."}
            )
        if failure == "rule":
            result = self._mutual_result(prompt)
            if _prompt_phase(prompt) == "opening":
                return result.model_copy(
                    update={
                        "question": TurnQuestion(
                            type="agent",
                            target_participant_id=_prompt_next_participant_id(prompt),
                            text="What do you think?",
                        )
                    }
                )
            return result.model_copy(update={"engagements": []})
        if failure == "matched_but_unused":
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
        if failure is not None:
            raise LLMProviderError("unknown mock failure injection")
        return self._mutual_result(prompt)

    def generate_segments(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        repair_feedback: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Emit a deterministic local v2 shape; this never calls a provider."""

        if not isinstance(snapshot, SegmentInputSnapshot):
            raise LLMStructuredOutputError("segment snapshot is invalid")
        del repair_feedback
        self.calls += 1
        system = build_segment_system_prompt(snapshot)
        self.call_log.append(
            MockLLMCall(
                prompt_hash=hashlib.sha256(
                    "\x1e".join((system, snapshot.to_user_json())).encode("utf-8")
                ).hexdigest(),
                receipt_hash=snapshot.receipt_hash,
                turn_id="",
                messages=(("system", system), ("user", snapshot.to_user_json())),
            )
        )
        failure = self._failures.popleft() if self._failures else None
        if failure == "technical":
            raise LLMProviderError("mock technical provider failure", acceptance_state="not_sent")
        if failure in {"json", "shape"}:
            raise LLMStructuredOutputError("mock malformed segment output")
        if failure == "long":
            return {"segments": [{"text": "x" * 8_001, "source_ids": [], "reply_to": None}]}
        if snapshot.discussion_json is not None:
            return self._four_round_segments(snapshot, failure=failure)
        source_ids = ["S1"] if snapshot.sources else []
        support_mode = "direct" if source_ids else "no_match"
        reply_to = (
            snapshot.barrages[0].id
            if snapshot.phase == "final_integration" and snapshot.barrages
            else None
        )
        if failure == "rule":
            reply_to = None
        if failure == "matched_but_unused":
            source_ids = []
            support_mode = "no_match"
        text = (
            (f'The record states, "{_complete_excerpt(snapshot.sources[0].text, max_words=24)}."')
            if source_ids
            else (
                f"{snapshot.persona.name} considers the topic carefully and keeps the response "
                "grounded in the discussion."
            )
        )
        segments: list[dict[str, object]] = [
            {
                "text": text,
                "source_ids": source_ids,
                "reply_to": None if source_ids and reply_to is not None else reply_to,
                "support_mode": support_mode,
            }
        ]
        if source_ids and reply_to is not None:
            segments.append(
                {
                    "text": "I will address the classroom question directly.",
                    "source_ids": [],
                    "reply_to": reply_to,
                    "support_mode": "no_match",
                }
            )
        return {"segments": segments}

    @staticmethod
    def _four_round_segments(
        snapshot: SegmentInputSnapshot, *, failure: str | None = None
    ) -> dict[str, object]:
        """Small authored offline fixtures, never a fallback for real generation."""

        discussion = snapshot.discussion
        if discussion is None:
            raise LLMStructuredOutputError("the teaching snapshot has no discussion context")
        agents = cast(list[dict[str, str]], discussion["agents"])
        peer = next(agent for agent in agents if agent["id"] != discussion["self_id"])
        if snapshot.round.number == 2:
            peer = next(
                agent for agent in agents if agent["id"] == discussion["question_target_id"]
            )
        received = cast(list[dict[str, str]], discussion["received_questions"])
        if snapshot.round.number == 3 and received:
            peer = next(agent for agent in agents if agent["id"] == received[0]["from_id"])
        peer_label = f"Agent {chr(65 + agents.index(peer))}"
        question_text = (
            "什么证据会让你修改所提出的保障措施？"
            if snapshot.language == "zh"
            else "What evidence would change your proposed safeguard?"
        )
        english = (
            "My main position is that classroom decisions should remain open to correction. "
            "The available material provides a limited starting point; it cannot establish how "
            "every community behaves. I distinguish that evidence boundary from my judgment "
            "that learners should explain why a claim follows from a source. A cultural "
            "perspective can suggest useful questions, but it cannot replace support. Where "
            "the record is incomplete, we should identify the missing information before "
            "treating a proposed classroom practice as reliable.",
            f"{peer_label}, I agree that a proposed safeguard needs an explicit reason. "
            "Your argument becomes less convincing if one example is treated as a universal "
            "rule. The evidence already shared can support a limited classroom trial, while "
            "the broader claim remains uncertain. I would add a condition: learners should "
            "record an outcome that could challenge the proposal. " + question_text,
            f"{peer_label}, a documented case in which the safeguard excludes a relevant "
            "perspective would make me change it. That answers the question about what "
            "could alter my position. I retain the proposal with a new condition: the "
            "class must check who can question its evidence and record any unanswered "
            "objection. The available material does not settle how often exclusion occurs. "
            "Your concern therefore changes the test I propose, without requiring either "
            "of us to claim that our present judgment is universally correct.",
            f"{peer_label}, I support your demand that a safeguard should remain open to "
            "challenge, because that makes its limits visible to the class. I still reject "
            "treating a single example as a rule for every culture. My final position is "
            "to try the proposal with an explicit opportunity to question its evidence. "
            "This discussion changed my criterion for success: participation now matters "
            "alongside the immediate result. We have a practical next step, while the "
            "unanswered question about who remains excluded preserves a reasonable disagreement.",
        )
        chinese = (
            "我的主要观点是，课堂判断应当允许根据证据修正。现有资料只能提供有限的观察起点，不能证明每个群体都会采用相同做法。"
            "我把资料能够支持的事实，与自己主张公开说明判断理由的建议分开。文化身份帮助我们提出问题，却不能代替事实依据。"
            "缺少资料时，应说明尚未知道什么，再决定是否尝试一种课堂安排，不能把个人理解包装成普遍规律。",
            f"{peer_label}，我认可你要求为保障措施说明理由的观点，但一个例子还不足以成为所有群体都应遵守的规则。"
            "已经公开的证据可以支持有限尝试，不能替我们排除其他解释。我建议记录可能挑战方案的结果，避免只有赞同意见得到重视。"
            + question_text,
            f"{peer_label}，如果出现有记录的案例，表明这项保障排除了相关意见，我会修改方案。这回答了什么证据能够改变判断的问题。"
            "我保留原来的建议，但增加条件：课堂必须检查谁能质疑证据，并记录尚未回答的异议。现有资料无法判断排除现象有多普遍。"
            "你的问题改变了我检验方案的标准，却不要求我们把当前判断说成必然正确。",
            f"{peer_label}，我赞同你提出让保障措施接受质疑的观点，因为这样能够让全班看见方案的限制。"
            "我仍反对把单一例子推广为所有文化的共同规则。最终立场是保留尝试，同时明确提出证据异议的机会。"
            "讨论使我把参与机会加入成功标准，不能只关注眼前结果。谁仍可能被排除尚未解决，我们可以据此继续观察，保留有理由的分歧。",
        )
        speech = (chinese if snapshot.language == "zh" else english)[snapshot.round.number - 1]
        reply_to = None
        if snapshot.round.number == 4 and snapshot.barrages:
            reply_to = snapshot.barrages[0].id
            speech += (
                "回应课堂提问：先公开判断标准，再记录反例，发现排除就调整。"
                if snapshot.language == "zh"
                else " To answer the classroom question, publish the criterion "
                "and revise the trial when an excluded perspective appears."
            )
        source_ids = ["S1"] if snapshot.sources and failure != "matched_but_unused" else []
        segment = {
            "text": "短。"
            if failure in {"short", "word"} and snapshot.language == "zh"
            else "Short."
            if failure in {"short", "word"}
            else speech,
            "source_ids": source_ids,
            "reply_to": None if failure == "rule" else reply_to,
            "support_mode": "contextual" if source_ids else "no_match",
        }
        question = (
            {"target_agent_id": discussion["question_target_id"], "text": question_text}
            if snapshot.round.number == 2
            else None
        )
        memory = (
            {
                "position": "Retain a revisable classroom trial.",
                "change": "qualified",
                "reason": "Check whose objections remain unanswered.",
                "influence": {
                    "agent_id": peer["id"],
                    "point": "Test who can challenge the evidence.",
                },
                "unresolved_question": "Who remains excluded?",
            }
            if snapshot.round.number == 3
            else None
        )
        if memory is not None and snapshot.language == "zh":
            memory.update(
                position="保留能够修正的课堂尝试。",
                reason="检查谁的异议仍未得到回答。",
                influence={"agent_id": peer["id"], "point": "检验谁能够质疑证据。"},
                unresolved_question="谁仍然可能被排除？",
            )
        return {"segments": [segment], "question": question, "discussion_memory": memory}

    def _mutual_result(
        self,
        prompt: MutualLearningPromptInput | ProviderPromptV1,
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
        position_value = (
            english_safe_dimension_value(
                dimensions.value_priority,
                fallback="the authored value priority",
            )
            if dimensions is not None
            else "the authored value priority"
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
                f"{getattr(speech_dimensions, 'debate_strategy_sentence', '')} "
                f"{speech_dimensions.question_style_sentence} "
            )
        )
        phase = prompt.phase
        source_claim = ""
        if used:
            source_claim = _safe_receipt_claim(prompt.receipts[0].text)
            evidence_line = f"{source_claim} I use it only as this participant's bounded evidence."
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
                source_sentence=(source_claim if used else None),
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
                    "accountable safeguards" + f", prioritizing {position_value}."
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
                source_sentence=(source_claim if used else None),
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
                    "affected-community correction path" + f", prioritizing {position_value}."
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
            source_sentence=(source_claim if used else None),
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
                "and community voice" + f", prioritizing {position_value}."
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


def validate_llm_provider_selector(selector: str) -> None:
    """Keep direct Mock construction separate from the reviewed real adapter."""

    if selector != "mock":
        raise RuntimeError("Use the reviewed provider factory for a real LLM adapter")


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
